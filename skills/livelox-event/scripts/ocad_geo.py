"""Georeferencing helper: map mm -> projected coordinates, using the OCAD map.

Reuses the parser in the sibling ocad-files skill.
"""
import math, os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', '..', 'ocad-files', 'scripts'))
from ocad import OcadFile  # noqa: E402


class Georeference:
    def __init__(self, ocd_path):
        self.ocd = OcadFile(ocd_path)
        s = self.ocd.setup
        self.scale = s['scale']
        self.angle = s['angle']
        self.x0, self.y0 = s['x0'], s['y0']
        self.epsg = int(s['epsg']) if s.get('epsg') else None
        self.realworld = bool(s['realworld'])

    def to_projected(self, x_mm, y_mm):
        f = self.scale / 1000.0
        a = math.radians(self.angle)
        ca, sa = math.cos(a), math.sin(a)
        return (x_mm * f * ca - y_mm * f * sa + self.x0,
                x_mm * f * sa + y_mm * f * ca + self.y0)

    def describe(self):
        return dict(scale=self.scale, angle=self.angle, epsg=self.epsg,
                    origin=(self.x0, self.y0), georeferenced=self.realworld)
