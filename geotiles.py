#!/usr/bin/env python3

import osmnx        # OpenStreetMap API
import pyproj       # Projection Library (EPSG:4326 <-> EPSG:32632)
import shapely      # Geometry Library
import pandas       # Pandas
import geopandas    # Pandas for Geodata
import tempfile     # Temporary files
import elevation    # Elevation data API
import pathlib
import subprocess

def calcuate_elevation(lbrt_bounds : tuple, elevation_step : int):
    # Create tempfiles
    tmp_geojson = pathlib.Path(tempfile.NamedTemporaryFile(suffix='.geojson').name)
    tmp_tif = pathlib.Path(tempfile.NamedTemporaryFile(suffix='.tif').name)

    # Fetch data
    elevation.clip(bounds=lbrt_bounds, output=tmp_tif)

    # Calculate contours
    subprocess.run([
        'gdal_contour',
        '-i', str(elevation_step),               # 5m interval
        '-amax', 'elevation',
        '-p', # Create polygons instead of polylines
        '-q', # quiet
        tmp_tif,
        tmp_geojson
    ])

    return geopandas.read_file(tmp_geojson)[['geometry', 'elevation']]

HEXAGON_SIZE = 650

TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32632", always_xy=True)
TO_LATLONG = pyproj.Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True)

def main():
    # GPS Coordinates (EPSG:4326)
    point = osmnx.geocoder.geocode('Groß Escherde')

    class Hexagon:
        def __init__(self, center : shapely.Point, size : float):
            self.center = center
            self.size = size
            self._streets_gdf = None
            self._elevation_gdf = None

        @property
        def polygon(self):
            x = self.center.x
            y = self.center.y

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
        def polygon_gdf(self):
            geopandas.GeoDataFrame({'type': ['hexagon'], 'geometry': [shapely.ops.transform(TO_LATLONG.transform, hexagon.polygon)]}, crs='EPSG:4326')

        def get_neighbours(self, tile_distance : int):
            ret = []

            pos = shapely.Point(
                self.center.x - self.size * 3 / 2 * tile_distance,
                self.center.y - self.size * tile_distance)

            directions = [(1, -1), (1, 1), (0, 2), (-1, 1), (-1, -1), (0, -2)]
            for i in range(0, 6):
                for j in range(0, tile_distance):
                    pos = shapely.Point(
                        pos.x + self.size * 3 / 2 * directions[i][0],
                        pos.y + self.size * directions[i][1])
                    ret.append(Hexagon(pos, self.size))

            return ret

        def get_elevation_gdf(self, step : int, elevation_minmax : tuple):
            if self._elevation_gdf is None:
                # Get transformed lbrt bounds (a bit larger, because of transformation errors)
                lbrt_bounds = shapely.ops.transform(
                    TO_LATLONG.transform,
                    self.center.buffer(self.size*1.1)).bounds

                gdf = calcuate_elevation(lbrt_bounds, step)

                # Clip all polygons inside gdf to this hexagon
                hexagon_poly = shapely.ops.transform(TO_LATLONG.transform, self.polygon)
                gdf['geometry'] = gdf.intersection(hexagon_poly)
                gdf = gdf[~gdf.is_empty] 

                gdf['type'] = 'elevation'

                # Loop over all rows and get 'elevation_min' and 'elevation_max' columns
                for i, row in gdf.iterrows():
                    if not row['geometry'].is_empty:
                        elevation_minmax[0] = min(elevation_minmax[0], row['elevation'])
                        elevation_minmax[1] = max(elevation_minmax[1], row['elevation'])

                self._elevation_gdf = gdf

            return self._elevation_gdf, elevation_minmax

        @property
        def streets_gdf(self):
            if self._streets_gdf is None:
                ll_poly = shapely.ops.transform(TO_LATLONG.transform, self.polygon)
                gdf = None
                try:
                    G = osmnx.graph_from_polygon(ll_poly, network_type='drive', simplify=False, truncate_by_edge=True, retain_all=True)
                    gdf = osmnx.graph_to_gdfs(G, nodes=False)

                    # Add lanes if it does not exist
                    gdf['lanes'] = gdf.get('lanes', 0)

                    # Drop all columns we are not interested in
                    gdf = gdf[['geometry', 'lanes']]
                    gdf['type'] = 'street'
                    gdf['lanes'].fillna(0, inplace=True)
                    gdf = gdf.convert_dtypes()

                    self._streets_gdf = gdf
                except ValueError as e:
                    # No streets in this hexagon
                    self._streets_gdf = geopandas.GeoDataFrame()
                except Exception as e:
                    print(f'Error: {e}')
                    print(gdf)
                    exit(1)

            return self._streets_gdf

        def create_utm_geojson(self, filename):
            ''' Create geojson file with UTM coordinates '''

            gdf = pandas.concat([
                self.polygon_gdf,
                self._elevation_gdf
            ], ignore_index=True)

            # Loop over all elevation polygons and clip the streets they contain
            # Add column with elevation to clipped streets
            for i, row in self._elevation_gdf.iterrows():
                if not row['geometry'].is_empty:
                    streets_gdf = self.streets_gdf.copy()
                    streets_gdf['geometry'] = streets_gdf.intersection(row['geometry'])
                    streets_gdf = streets_gdf[~streets_gdf.is_empty]
                    streets_gdf['elevation'] = row['elevation']
                    gdf = pandas.concat([gdf, streets_gdf], ignore_index=True)

            gdf = gdf.to_crs('EPSG:32632')
            gdf.to_file(filename)

    # Create hexagon around point.
    point_utm = TO_UTM.transform(point[1], point[0])
    hexagon_center = Hexagon(shapely.geometry.Point(point_utm), HEXAGON_SIZE)

    # Create hexagons around center
    hexagons = [hexagon_center]
    for i in range(1, 1):
        hexagons.extend(hexagon_center.get_neighbours(i))

    # Create overall geojson
    gdfs = []
    elevation_bounds = [float('inf'), float('-inf')]
    for hexagon in hexagons:
        elevation_gdf, elevation_bounds = hexagon.get_elevation_gdf(5, elevation_bounds)
        gdfs.append(elevation_gdf)
        gdfs.append(hexagon.streets_gdf)
        gdfs.append(hexagon.polygon_gdf)
    gdf = pandas.concat(gdfs, ignore_index=True)
    print(gdf)
    print(f'Elevation min: {elevation_bounds[0]}, max: {elevation_bounds[1]}')
    gdf.to_file('out.geojson')

    # Create SVG per hexagon
    for i, hexagon in enumerate(hexagons):
        hexagon.create_utm_geojson(f'hexagon_{i}.geojson')

if __name__ == '__main__':
    main()
