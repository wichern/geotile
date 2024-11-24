#!/usr/bin/env python3

__copyright__ = "Copyright 2024, Paul Wichern"

import osmnx as ox
import math
import json
import elevation
import subprocess
from pathlib import Path

LATITUDE = 0
LONGITUDE = 1

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

    def add_feature(self, feature):
        self.json['features'].append(feature)

    def save(self, path):
        with open(path, 'w') as outfile:
            outfile.write(json.dumps(self.json, indent=2))

def create_bbox(center, size):
    # In the Mercator projection, we have to use a smaller latitude in order to get a square.
    long_multiplier = math.cos(math.radians(center[LATITUDE]))
    # print(f'longitude multiplier: {long_multiplier}')

    return [
        center[LATITUDE] + size/2*long_multiplier, # north / ymax
        center[LATITUDE] - size/2*long_multiplier, # south / ymin
        center[LONGITUDE] + size/2, # east / xmax
        center[LONGITUDE] - size/2  # west / xmin
    ]

def fetch_streets(bbox, geojson):
    G = ox.graph_from_bbox(None, None, None, None,
            bbox, 'drive', simplify=False, truncate_by_edge=True, retain_all=False)
    
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
        '-i', '5',               # 1m interval
        '-a', 'elevation',
        Path.cwd()/'region_dem.tif',
        Path.cwd()/'contours.geojson'
    ])
    
    with open(Path.cwd()/'contours.geojson', 'r') as json_in:
        data = json.load(json_in)

        for feature in data['features']:
            feature['properties']['stroke'] = '#00ff00'
            feature['properties']['stroke-width'] = '1'
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

    # Create geojson
    geojson = GeoJSON()
    geojson.add_bbox(square_bounds)
    fetch_streets(square_bounds, geojson)
    fetch_landuse(square_bounds, geojson, 'residential')
    fetch_elevation(square_bounds, geojson)
    geojson.save('tile.geojson')


