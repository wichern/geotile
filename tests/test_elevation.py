#!/usr/bin/env python3
# -*- coding: utf-8 -*-
 
import unittest
from pathlib import Path
import pytest

from geotiles import Elevation

@pytest.mark.skip(reason='long running test')
class ElevationTest(unittest.TestCase):
    def testDefault(self):
        elevation = Elevation(clear_cache=False)
        elevation.create_geojson((12.35, 41.8, 12.65, 42), 10, Path.cwd()/'_tmp'/'test.geojson')
