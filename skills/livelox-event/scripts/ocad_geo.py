"""Georeferencing helper: map mm -> projected coordinates, using the OCAD map.

Reuses the parser in the sibling ocad-files skill.
"""
import math, os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', '..', 'ocad-files', 'scripts'))
from ocad import OcadFile, paper_to_real  # noqa: E402


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
        return paper_to_real(self.ocd.setup, x_mm, y_mm)

    def to_wgs84(self, x_mm, y_mm):
        """(lengdegrad, breddegrad), eller None om systemet ikke er UTM."""
        return utm_to_wgs84(*self.to_projected(x_mm, y_mm), self.epsg)

    def describe(self):
        return dict(scale=self.scale, angle=self.angle, epsg=self.epsg,
                    origin=(self.x0, self.y0), georeferenced=self.realworld)


def utm_zone(epsg):
    """(sone, nordlig halvkule) for UTM-systemene, ellers None.

    326zz/327zz er WGS84 UTM nord/sør, 258zz er ETRS89 UTM - for våre formål
    det samme som WGS84 (forskjellen er under en meter).
    """
    e = int(epsg or 0)
    if 32601 <= e <= 32660:
        return e - 32600, True
    if 32701 <= e <= 32760:
        return e - 32700, False
    if 25801 <= e <= 25860:
        return e - 25800, True
    return None


def utm_to_wgs84(easting, northing, epsg):
    """UTM -> (lengdegrad, breddegrad) i grader, uten eksterne bibliotek.

    Krügers serier (Karney 2011) til sjette orden - nøyaktig på
    millimeternivå innenfor sonen, mer enn godt nok for poster.
    """
    z = utm_zone(epsg)
    if not z:
        return None
    zone, north = z
    a, f = 6378137.0, 1 / 298.257223563
    n = f / (2 - f)
    A = a / (1 + n) * (1 + n**2 / 4 + n**4 / 64 + n**6 / 256)
    beta = (n / 2 - 2 * n**2 / 3 + 37 * n**3 / 96 - n**4 / 360 - 81 * n**5 / 512 + 96199 * n**6 / 604800,
            n**2 / 48 + n**3 / 15 - 437 * n**4 / 1440 + 46 * n**5 / 105 - 1118711 * n**6 / 3870720,
            17 * n**3 / 480 - 37 * n**4 / 840 - 209 * n**5 / 4480 + 5569 * n**6 / 90720,
            4397 * n**4 / 161280 - 11 * n**5 / 504 - 830251 * n**6 / 7257600,
            4583 * n**5 / 161280 - 108847 * n**6 / 3991680,
            20648693 * n**6 / 638668800)
    k0 = 0.9996
    xi = (northing - (0 if north else 10000000.0)) / (k0 * A)
    eta = (easting - 500000.0) / (k0 * A)
    xi_ = xi - sum(b * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, b in enumerate(beta, 1))
    eta_ = eta - sum(b * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, b in enumerate(beta, 1))
    chi = math.asin(math.sin(xi_) / math.cosh(eta_))
    # konform breddegrad -> geodetisk breddegrad (Newton på tau)
    e = math.sqrt(f * (2 - f))
    tau_ = math.tan(chi)
    tau = tau_
    for _ in range(5):
        sigma = math.sinh(e * math.atanh(e * tau / math.sqrt(1 + tau**2)))
        tau_i = tau * math.sqrt(1 + sigma**2) - sigma * math.sqrt(1 + tau**2)
        dtau = ((tau_ - tau_i) / math.sqrt(1 + tau_i**2)
                * (1 + (1 - e**2) * tau**2) / ((1 - e**2) * math.sqrt(1 + tau**2)))
        tau += dtau
        if abs(dtau) < 1e-12:
            break
    lat = math.degrees(math.atan(tau))
    lon0 = (zone - 1) * 6 - 180 + 3
    lon = lon0 + math.degrees(math.atan2(math.sinh(eta_), math.cos(xi_)))
    return lon, lat


def map_extent(ocd):
    """(venstre, bunn, høyre, topp) i papir-mm for alle synlige objekter i kartet.

    Leser bare objektindeksen, der OCAD lagrer hvert objekts omsluttende
    rektangel - ikke selve objektene. Det holder for å avsløre poster som
    havner utenfor kartet, og går raskt også på kart på 60 MB. None om kartet
    ikke har objekter.
    """
    import struct
    o = ocd if hasattr(ocd, 'b') else OcadFile(ocd)
    b, off, seen = o.b, o.obj_idx, set()
    L = B = float('inf'); R = T = float('-inf')
    while off and off not in seen and off + 4 <= len(b):
        seen.add(off)
        nxt, = struct.unpack_from('<i', b, off)
        for i in range(256):
            p = off + 4 + i * 40
            if p + 40 > len(b):
                break
            pos, = struct.unpack_from('<i', b, p + 16)
            status = b[p + 30]
            if pos <= 0 or status != 1:
                continue
            l, bo, r, t = ((v >> 8) / 100.0 for v in struct.unpack_from('<iiii', b, p))
            L, B, R, T = min(L, l), min(B, bo), max(R, r), max(T, t)
        off = nxt if nxt > 0 else 0
    return None if L == float('inf') else (L, B, R, T)
