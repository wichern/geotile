#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import elevation
from pathlib import Path
import subprocess

class Elevation:
     __tmpfile_tif = output=Path.cwd()/'region_dem.tif'

     def __init__(self, *, clear_cache=False):
          if clear_cache:
               elevation.clean()
     
     def create_geojson(self, lbrt_bounds, elevation_step, dest):
        '''
        Generate geojson features with elevation polygons.

        Expecting bounding box with (left, bottom, right, top)
        Elevation step in meters
        '''

        # Create dest dir
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Fetch data
        elevation.clip(bounds=lbrt_bounds, output=self.__tmpfile_tif)

        # Calculate contours
        subprocess.run([
            'gdal_contour',
            '-i', str(elevation_step),               # 5m interval
            '-amin', 'elevation_min',
            '-amax', 'elevation_max',
            '-p', # Create polygons instead of polylines
            '-q', # quiet
            self.__tmpfile_tif,
            dest
        ])
