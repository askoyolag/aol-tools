"""Georeferencing helper: map mm -> projected coordinates, using the OCAD map.

Reuses the parser in the sibling ocad-files skill.
"""
import math, os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', '..', 'ocad-files', 'scripts'))
from ocad import OcadFile  # noqa: E402


def epsg_from_setup(s):
    """EPSG code for the map, from the declared code or OCAD's own grid id.

    OCAD stores its coordinate system as an internal id in `i`, and - in newer
    files - the EPSG code in `e`. Ids 2001-2060 are the WGS84 UTM zones, so
    i=2032 (UTM 32N, the usual one on Askøy) is EPSG:32632; that holds for every
    map in the club archive that declares both. Id 1000 means no coordinate
    system at all.
    """
    e = s.get('epsg')
    if e and str(e).strip() not in ('', '0'):
        return int(e)
    grid = s.get('grid')
    if grid and 2001 <= int(grid) <= 2060:
        return 32600 + int(grid) - 2000
    return None


class Georeference:
    def __init__(self, ocd_path, epsg=None):
        self.ocd = OcadFile(ocd_path)
        s = self.ocd.setup
        self.scale = s['scale']
        self.angle = s['angle']
        self.x0, self.y0 = s['x0'], s['y0']
        self.declared_epsg = s.get('epsg')
        self.epsg = epsg or epsg_from_setup(s)
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
