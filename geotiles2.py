#!/usr/bin/env python3

__copyright__ = "Copyright 2024, Paul Wichern"

import argparse
import osmnx
from pathlib import Path
import geopandas
import shapely
import numpy as np

import geotiles

def main():
    # Set up the argument parser
    parser = argparse.ArgumentParser(description="Process input string and output directory with tile size and elevation step options.")
    
    # Positional arguments
    parser.add_argument("CENTER_QUERY", type=str, help="Location to use as center")
    parser.add_argument("OUT_DIR", type=Path, help="Path to the output directory")
    
    # Optional arguments
    parser.add_argument("--tile-size", "-s", type=int, default=1000, 
                        help="Tile size in meters (default: 1000)")
    parser.add_argument("--total-area-size", "-t", type=int, default=2000000, 
                        help="Total available area size (default: 20000)")
    parser.add_argument("--elevation-step", "-e", type=int, default=10, 
                        help="Elevation step in meters (default: 10)")
    
    # Parse the arguments
    args = parser.parse_args()

    # Process the arguments
    elevation_step = args.elevation_step

    # Ensure the output directory exists
    args.OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Query the location of the center
    center_location = osmnx.geocoder.geocode(args.CENTER_QUERY)

    # Create overall bounds (left, bottom, right, top)
    bbox = osmnx.utils_geo.bbox_from_point(center_location, args.total_area_size)
    
    geodata = { 'name': ['Bounds'], 'geometry': [osmnx.utils_geo.bbox_to_poly(bbox)] }

    # Create hex grid
    hexagons = geotiles.distribute_hexagons(bbox, 1)
    for hexagon in hexagons:
        geodata['name'].append('Hexagon')
        geodata['geometry'].append(hexagon.polygon)

        #geodata['geometry'].append(hexagon.center.buffer(0.01, 1.75))

        # geodata['name'].append('Circle')
        # geodata['geometry'].append(hexagon.center.buffer(0.01))

        

    gdf = geopandas.GeoDataFrame(geodata, crs='EPSG:4326')
    gdf.to_file(args.OUT_DIR/'bounds_total.geojson')

if __name__ == '__main__':
    main()
