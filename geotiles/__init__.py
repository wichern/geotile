#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from geotiles.elevation import *

import shapely
import math

class Hexagon:
    '''
    flat top hexagon
    '''

    def __init__(self, center, size):
        '''
        :param: center (shapely.geometry.Point)
        :param: size Radius of the outer circle
        '''
        self.center = center
        self.size = size

    # @property
    # def width(self):
    #     return 3 / 2 * self.size

    # @property
    # def heigth(self):
    #     return math.sqrt(3) * self.size

    @property
    def polygon(self):
        x = self.center.x
        y = self.center.y

        return shapely.geometry.Polygon(
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
    def bbox(self):
        ''' (left, bottom, right, top) '''
        return (
            self.center.x - self.size,
            self.center.y - self.size,
            self.center.x + self.size,
            self.center.y + self.size
        )

def distribute_hexagons(bbox, hexagon_size):
    '''
    bbox (left, bottom, right, top)
    '''

    hexagons = []

    x_min = bbox[0]
    y_min = bbox[1]
    x_max = bbox[2]
    y_max = bbox[3]

    horizontal_distance = 3*hexagon_size
    vertical_distance = hexagon_size

    x = x_min
    y = y_min
    even = True
    while True:
        center = shapely.geometry.Point(x + hexagon_size, y + hexagon_size)
        hexagons.append(Hexagon(center, hexagon_size))

        x = x + horizontal_distance
        if x + hexagon_size > x_max:
            if even:
                x = x_min + horizontal_distance/2
            else:
                x = x_min
            even = not even
            y = y + vertical_distance
            if y + hexagon_size > y_max:
                return hexagons
