#!/usr/bin/env python3

import argparse
import elevation    # Elevation data API
import geopandas    # Pandas for Geodata
import osmnx        # OpenStreetMap API
from typing import List
import pandas       # Pandas
import pathlib
import pyproj       # Projection Library (EPSG:4326 <-> EPSG:32632)
import shapely      # Geometry Library
import subprocess
import tempfile     # Temporary files
import trimesh
import numpy

TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32632", always_xy=True)
TO_LATLONG = pyproj.Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True)

def compute_normalization_params(geom : shapely.geometry.base.BaseGeometry, target_size : float):
    minx = geom.bounds[0]
    miny = geom.bounds[1]
    maxx = geom.bounds[2]
    maxy = geom.bounds[3]

    width = maxx - minx
    height = maxy - miny

    scale = target_size / max(width, height)

    return {'xoff': -minx, 'yoff': -miny, 'scale': scale}

def apply_normalization(geom: shapely.geometry.base.BaseGeometry, params):
    translated = shapely.affinity.translate(geom, xoff=params['xoff'], yoff=params['yoff'])
    return shapely.affinity.scale(translated, xfact=params['scale'], yfact=params['scale'], origin=(0,0))

class Hexagon:
    def __init__(self, center_utm : shapely.Point, size : float):
        self.center_utm = center_utm
        self.size = size
        
        # every Hexagon contains a single row GeoDataFrame
        data = {
            'type': ['Hexagon'],
            'geometry': [self.polygon_utm]
        }
        self.gdf = geopandas.GeoDataFrame(data, crs='EPSG:32632')
        self.elevation_gdf = geopandas.GeoDataFrame()
        self.streets_gdf = geopandas.GeoDataFrame()

    @property
    def polygon_utm(self) -> shapely.Polygon:
        ''' Get polygon of the hexagon '''
        x = self.center_utm.x
        y = self.center_utm.y

        return shapely.Polygon(
            [
                (x - self.size/2, y + self.size),
                (x - self.size, y),
                (x - self.size/2, y - self.size),
                (x + self.size/2, y - self.size),
                (x + self.size, y),
                (x + self.size/2, y + self.size),
                (x - self.size/2, y + self.size)
            ]
        )

    @property
    def polygon_latlong(self) -> shapely.Polygon:
        return shapely.ops.transform(TO_LATLONG.transform, self.polygon_utm)
    
    def get_lbrt_bounds_utm(self, expand : float=1.0) -> shapely.Polygon:
        return self.center_utm.buffer(self.size * expand).bounds
    
    def get_lbrt_bounds_latlong(self, expand : float=1.0) -> shapely.Polygon:
        return shapely.ops.transform(
            TO_LATLONG.transform, self.center_utm.buffer(self.size * expand)).bounds
    
    def get_neighbours(self, tile_distance : int) -> List['Hexagon']:
        ''' Get list of neighbours in ring of given distance '''
        ret = []

        pos = shapely.Point(
            self.center_utm.x - self.size * 3 / 2 * tile_distance,
            self.center_utm.y - self.size * tile_distance)

        directions = [(1, -1), (1, 1), (0, 2), (-1, 1), (-1, -1), (0, -2)]
        for i in range(0, 6):
            for j in range(0, tile_distance):
                pos = shapely.Point(
                    pos.x + self.size * 3 / 2 * directions[i][0],
                    pos.y + self.size * directions[i][1])
                ret.append(Hexagon(pos, self.size))

        return ret
    
    def fetch_data(self, elevation_step : int):
        self._fetch_elevation(elevation_step)
        self._fetch_streets()

        # Loop over all elevation polygons and clip the streets they contain
        # Add column with elevation to clipped streets
        if not self.streets_gdf.empty and not self.elevation_gdf.empty:
            clipped_gdfs = []
            
            # Loop over elevation polygons
            for _, elev_row in self.elevation_gdf.iterrows():
                streets_clip = self.streets_gdf.copy()
                streets_clip['geometry'] = streets_clip.geometry.intersection(elev_row['geometry'])
                streets_clip = streets_clip[~streets_clip.geometry.is_empty].copy()
                streets_clip['elevation'] = elev_row['elevation']
                clipped_gdfs.append(streets_clip)
            
            # Concatenate all clipped street GeoDataFrames at once
            if clipped_gdfs:
                self.streets_gdf = pandas.concat(clipped_gdfs, ignore_index=True)
            else:
                self.streets_gdf = geopandas.GeoDataFrame(columns=self.streets_gdf.columns.tolist() + ['elevation'])
                
            assert self.streets_gdf.crs.to_string() == 'EPSG:32632', f'Expected CRS EPSG:32632, got {self.streets_gdf.crs}'

    def _fetch_elevation(self, step : int):
        ''' Fetch elevation data and add column to internal geodata frame.

        :step: Elevation step size in meters 
        '''

        # Fetch data (increase bounds because of transformation errors)
        tmp_tif = pathlib.Path(tempfile.NamedTemporaryFile(suffix='.tif').name)
        elevation.clip(bounds=self.get_lbrt_bounds_latlong(1.1), output=tmp_tif)

        # Calculate contours
        tmp_geojson = pathlib.Path(tempfile.NamedTemporaryFile(suffix='.geojson').name)
        subprocess.run(
            [
                'gdal_contour',
                '-i', str(step),               # 5m interval
                '-amax', 'elevation',
                '-p', # Create polygons instead of polylines
                '-q', # quiet
                tmp_tif,
                tmp_geojson
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True)
        
        # Read tmp geojson file and extract columns 'geometry' and 'elevation'
        self.elevation_gdf = geopandas.read_file(tmp_geojson)[['geometry', 'elevation']]

        # Clip all polygons inside gdf to this hexagon
        self.elevation_gdf['geometry'] = self.elevation_gdf.intersection(self.polygon_latlong)

        # Drop all rows from elevation_gdf whose geometries are empty after the intersection step.
        self.elevation_gdf = self.elevation_gdf[~self.elevation_gdf.geometry.is_empty]

        self.elevation_gdf = self.elevation_gdf.to_crs("EPSG:32632")

    def _fetch_streets(self):
        try:
            G = osmnx.graph_from_polygon(self.polygon_latlong, network_type='drive', simplify=False, truncate_by_edge=True, retain_all=True)
            gdf = osmnx.graph_to_gdfs(G, nodes=False)

            # Add lanes if it does not exist
            gdf['lanes'] = gdf.get('lanes', 0)

            # Drop all columns we are not interested in
            gdf = gdf[['geometry', 'lanes']]
            gdf['type'] = 'street'
            gdf['lanes'] = gdf['lanes'].fillna(0)
            gdf = gdf.convert_dtypes()

            self.streets_gdf = gdf.to_crs("EPSG:32632")
        except ValueError as e:
            # No streets in this hexagon
            pass
        except Exception as e:
            print(f'Error: {e}')
            exit(1)

    def create_geojson(self, filename, encoding='EPSG:32632'):
        gdf = pandas.concat([
            self.gdf, self.elevation_gdf, self.streets_gdf
        ], ignore_index=True)
        gdf = gdf.to_crs(encoding)
        gdf.to_file(filename)

    
    def export_mesh(self, filename, diameter_mm, base_height_mm, elevation_scale : float, elevation_offset_m):
        """
        Create a 3D model from elevation polygons in self.elevation_gdf.
        
        Parameters:
            filename (str): Output 3MF file path
            diameter_mm (float): Diameter of the overall model (for scaling XY)
            base_height_mm (float): Base thickness in mm
            elevation_scale (float): Multiplier to convert elevation units to mm
            elevation_offset_m (float): Base elevation offset in m
        """

        GREEN = [0, 255, 0, 255]  # RGBA

        normalization_params = compute_normalization_params(self.polygon_utm, diameter_mm)
        
        meshes = []

        # The polygon has no interiour rings. Only exteriors.
        hexagon_poly = apply_normalization(self.polygon_utm, normalization_params)
        mesh = trimesh.creation.extrude_polygon(hexagon_poly, base_height_mm)
        meshes.append(mesh)

        # TODO: extre the last X mm in the color of the lowest elevation type
        

        # Elevations
        for _, elev_row in self.elevation_gdf.iterrows():
            elev_poly = elev_row['geometry']
            elev_height = elev_row['elevation'] - elevation_offset_m

            if elev_height == 0.0:
                continue

            elev_polys = []
            if isinstance(elev_poly, shapely.Polygon):
                elev_polys = [elev_poly]
            elif isinstance(elev_poly, shapely.MultiPolygon):
                elev_polys = elev_poly.geoms
            else:
                continue

            for poly in elev_polys:
                normalized_poly = apply_normalization(poly, normalization_params)
                mesh = trimesh.creation.extrude_polygon(normalized_poly, elevation_scale * elev_height)
                mesh.apply_translation([0, 0, base_height_mm])
                mesh.visual.vertex_colors = numpy.tile(GREEN, (len(mesh.vertices), 1))
                # TODO: color based on elevation (water, green, rough (above vegatation) snow)
                #       and land use
                meshes.append(mesh)
        
        combined = trimesh.util.concatenate(meshes)
        combined.export(filename)

    @property
    def min_elevation(self):
        return self.elevation_gdf['elevation'].min()

    @property
    def max_elevation(self):
        return self.elevation_gdf['elevation'].max()

def main():
    parser = argparse.ArgumentParser(description="Process input string and output directory with tile size and elevation step options.")
    
    # Positional arguments
    parser.add_argument("CENTER_QUERY", type=str, help="Location to use as center")
    
    # Optional arguments
    parser.add_argument("--tile-size-meters", "-tm", type=int, default=650,
                        help="Tile size in meters (input) (default: 650)")
    parser.add_argument("--hexagon-radius", "-r", type=int, default=0,
                        help="Number of hexagons in each direction (default: 0)")
    parser.add_argument("--tile-size-millimeters", "-tmm", type=int, default=100,
                        help="3MF tile size in millimeters o(default: 100)")
    parser.add_argument("--elevation-step-meters", "-em", type=int, default=1, 
                        help="Elevation step in meters (default: 1)")
    parser.add_argument("--elevation-step-millimeters", "-emm", type=float, default=0.1,
                        help="3MF elevation step in millimeters (default: 0.1)")
    parser.add_argument("--out-dir", "-o", type=pathlib.Path, default=pathlib.Path('out/'),
                        help="Output directory (default: out/)")

    args = parser.parse_args()

    # GPS Coordinates (EPSG:4326)
    point = osmnx.geocoder.geocode(args.CENTER_QUERY)

    # Create hexagon tile around point.
    point_utm = TO_UTM.transform(point[1], point[0])
    hexagon_center = Hexagon(shapely.geometry.Point(point_utm), args.tile_size_meters)

    # Create neighbouring tiles
    hexagons = [hexagon_center]
    for i in range(args.hexagon_radius):
        hexagons.extend(hexagon_center.get_neighbours(i + 1))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    min_elevation = float('inf')
    max_elevation = float('-inf')
    for i, hexagon in enumerate(hexagons):
        hexagon.fetch_data(args.elevation_step_meters)
        min_elevation = min(min_elevation, hexagon.min_elevation)
        max_elevation = max(max_elevation, hexagon.max_elevation)

        hexagon.create_geojson(args.out_dir / f'hexagon_{i}.utm.geojson', 'EPSG:32632')
        hexagon.create_geojson(args.out_dir / f'hexagon_{i}.latlong.geojson', 'EPSG:4326')

    for i, hexagon in enumerate(hexagons):
        hexagon.export_mesh(args.out_dir / f'hexagon_{i}.glb',
                           args.tile_size_millimeters,
                           10,
                           float(args.elevation_step_millimeters) / float(args.elevation_step_meters),
                           min_elevation)

    # TODO: Create overwall geojson
    # TODO: Create overall 3MF file

if __name__ == '__main__':
    main()
