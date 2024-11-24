#!/usr/bin/env python3

__copyright__ = "Copyright 2024, Paul Wichern"

import osmnx as ox
import math
import json
import elevation
import subprocess
from pathlib import Path
import shapely.geometry
import numpy as np

LATITUDE = 0
LONGITUDE = 1

TILE_SIZE_METERS = 1000
ELEVATION_LINE_METERS = 15

def simplify(polygon, tolerance = 0.00001):
    """ Simplify a polygon with shapely.
    Polygon: ndarray
        ndarray of the polygon positions of N points with the shape (N,2)
    tolerance: float
        the tolerance
    """
    for i in range(0, len(polygon)):
        for j in range(0, len(polygon[i])):
            print(polygon[i][j])
            poly = shapely.geometry.Polygon(polygon[i][j])
            poly_s = poly.simplify(tolerance=tolerance)
            # convert it back to numpy
            polygon[i][j] = poly_s.boundary.coords[:]
    return polygon

def nonmax(a, b):
    if a == None:
        return b
    if b == None:
        return a
    return max(a, b)

def nonmin(a, b):
    if a == None:
        return b
    if b == None:
        return a
    return min(a, b)

class GeoJSON:
    def __init__(self):
        self.json = { 'type': 'FeatureCollection', 'features': [] }

    def add_bbox(self, bbox):
        feature = { 
            'type': 'Feature',
            'geometry': {
                'type': 'LineString',
                'coordinates': [
                    [bbox[2], bbox[0]],
                    [bbox[2], bbox[1]],
                    [bbox[3], bbox[1]],
                    [bbox[3], bbox[0]],
                    [bbox[2], bbox[0]]
                ]
            },
            'properties': {
                'stroke': '#0000ff',
                'stroke-width': 1
            }
        }
        self.json['features'].append(feature)
        self.json['metadata'] = {
            'x_min': bbox[3],
            'y_min': bbox[1],
            'x_scale': 10 / (bbox[2] - bbox[3]),
            'y_scale': 10 / (bbox[0] - bbox[1])
        }

    def add_feature(self, feature):
        self.json['features'].append(feature)

    def save(self, path):
        with open(path, 'w') as outfile:
            outfile.write(json.dumps(self.json, indent=2))

def create_bbox(center, size):
    # In the Mercator projection, we have to use a smaller latitude in order to get a square.
    long_multiplier = math.cos(math.radians(center[LATITUDE]))
    print(f'longitude multiplier: {long_multiplier}')

    return [
        center[LATITUDE] + size/2*long_multiplier, # north / ymax
        center[LATITUDE] - size/2*long_multiplier, # south / ymin
        center[LONGITUDE] + size/2, # east / xmax
        center[LONGITUDE] - size/2  # west / xmin
    ]

def fetch_streets(bbox, geojson):
    G = ox.graph_from_bbox(None, None, None, None,
            bbox, 'drive', simplify=False, truncate_by_edge=True, retain_all=True)
    
    # Convert to GeoDataFrame
    edges = ox.graph_to_gdfs(G, nodes=False)  # Get edges

    for edge in edges.itertuples():
        lanes = getattr(edge, 'lanes', '1')
        if math.isnan(float(lanes)):
            lanes = '1'

        feature = { 
            'type': 'Feature',
            'geometry': {
                'type': 'LineString',
                'coordinates': list(edge.geometry.coords)
            },
            'properties': {
                'lanes': lanes
            }
        }
        geojson.add_feature(feature)

def fetch_landuse(bbox, geojson, type='residential'):
    features = ox.features_from_bbox(None, None, None, None, bbox, {'landuse': type})
    
    for feature in features.itertuples():
        json_feature = { 
            'type': 'Feature',
            'geometry': {
                'type': 'LineString',
                'coordinates': list(feature.geometry.exterior.coords)
            },
            'properties': {
                'type': type,
                'stroke': '#ff0000',
                'stroke-width': 1
            }
        }
        geojson.add_feature(json_feature)

def transform_polygon(polygon, bbox, x_offset, y_offset, x_scale, y_scale):
    return [ [ [ [coord[0] + x_offset + (coord[0] - bbox[3])*x_scale - (coord[0] - bbox[3]), coord[1] + y_offset + (coord[1] - bbox[1])*y_scale - (coord[1] - bbox[1])] for coord in ring ] for ring in p ] for p in polygon]

def fetch_elevation(bbox, geojson, clean=False):
    if clean:
        elevation.clean()

    # Fetch DEM from NASA servers
    elevation.clip(bounds=(
        bbox[3], bbox[1], bbox[2], bbox[0]
    ), output=Path.cwd()/'region_dem.tif')

    # Generate contours
    subprocess.run([
        'gdal_contour',
        '-i', str(ELEVATION_LINE_METERS),               # 5m interval
        '-amin', 'elevation_min',
        '-amax', 'elevation_max',
        '-p', # Create polygons instead of polylines
        '-q', # Quit
        Path.cwd()/'region_dem.tif',
        Path.cwd()/'contours.geojson'
    ])
    
    with open(Path.cwd()/'contours.geojson', 'r') as json_in:
        data = json.load(json_in)

        # The coordinates do not perfectly match. We transform them so that they do.
        # 1. Get min and max
        min_x = None
        min_y = None
        max_x = None
        max_y = None
        for feature in data['features']:
            for polygons in feature['geometry']['coordinates']:
                for polygon in polygons:
                    for coord in polygon:
                        min_y = nonmin(coord[LONGITUDE], min_y)
                        max_y = nonmax(coord[LONGITUDE], max_y)
                        min_x = nonmin(coord[LATITUDE], min_x)
                        max_x = nonmax(coord[LATITUDE], max_x)

        height_bbox = bbox[0] - bbox[1]
        width_bbox = bbox[2] - bbox[3]
        print(f'width_bbox = {width_bbox}, height_bbox = {height_bbox}')

        width_elev = max_x - min_x
        height_elev = max_y - min_y
        print(f'width_elev = {width_elev}, height_elev = {height_elev}')

        width_scale = width_bbox / width_elev
        heigth_scale = height_bbox / height_elev

        print(f'min_x = {min_x}, bbox[3] = {bbox[3]}')
        print(f'min_y = {min_y}, bbox[1] = {bbox[1]}')

        translate_x = -(min_x - bbox[3])
        translate_y = -(min_y - bbox[1])

        print(f'width_scale = {width_scale}')

        for feature in data['features']:
            feature['properties']['stroke'] = '#00ff00'
            feature['properties']['stroke-width'] = '1'
            feature['geometry']['coordinates'] = transform_polygon(feature['geometry']['coordinates'], bbox, translate_x, translate_y, width_scale, heigth_scale)

            simplify(feature['geometry']['coordinates'])

            geojson.add_feature(feature)

if __name__ == '__main__':
    center_query = 'Groß Escherde'
    square_size_km = 3
    square_size = square_size_km / 1.852 / 60

    # Get geo coordinates
    print(f'Get location of "{center_query}" ...', end=" ")
    center_location = ox.geocoder.geocode(center_query) # lat (y), long (x)
    print(center_location)

    square_bounds = create_bbox(center_location, square_size)
    square_bounds = ox.utils_geo.bbox_from_point(center_location, dist=TILE_SIZE_METERS)
    print(square_bounds)

    # Create geojson
    geojson = GeoJSON()
    geojson.add_bbox(square_bounds)
    fetch_streets(square_bounds, geojson)
    fetch_landuse(square_bounds, geojson, 'residential')
    fetch_elevation(square_bounds, geojson)
    geojson.save('tile.geojson')


