"""Minimal reader for OCAD .ocd files (v9-2018+) + map area estimation."""
import struct, math, os

OCAD_MARK = 0x0CAD

class OcadFile:
    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            self.b = f.read()
        b = self.b
        (self.mark, self.ftype, self.fstatus, self.version,
         self.sub, self.subsub, self.sym_idx, self.obj_idx) = struct.unpack_from('<hBBhBBII', b, 0)
        if self.mark != OCAD_MARK:
            raise ValueError('Not an OCAD file: %s' % path)
        self.str_idx, = struct.unpack_from('<I', b, 32)
        self._strings = None

    # ---------- parameter strings ----------
    @property
    def strings(self):
        if self._strings is None:
            out = []
            off = self.str_idx
            b = self.b
            seen = set()
            while off and off not in seen and off < len(b):
                seen.add(off)
                nxt, = struct.unpack_from('<I', b, off)
                for i in range(256):
                    p = off + 4 + i * 16
                    if p + 16 > len(b): break
                    pos, ln, rectype, objidx = struct.unpack_from('<iiii', b, p)
                    if pos <= 0 or ln <= 0: continue
                    raw = b[pos:pos + ln].split(b'\x00', 1)[0]
                    out.append((rectype, objidx, raw.decode('cp1252', 'replace')))
                off = nxt
            self._strings = out
        return self._strings

    def param(self, rectype):
        """Return list of dicts {'':first, 'm':..} for given record type."""
        res = []
        for rt, oi, s in self.strings:
            if rt != rectype: continue
            parts = s.split('\t')
            d = {'': parts[0]}
            for p in parts[1:]:
                if p: d[p[0]] = p[1:]
            res.append(d)
        return res

    # ---------- georeferencing ----------
    @property
    def setup(self):
        p = self.param(1039)
        d = p[0] if p else {}
        def f(k, dflt=0.0):
            try: return float(d.get(k, dflt))
            except ValueError: return dflt
        return dict(scale=f('m', 0.0), angle=f('a', 0.0),
                    x0=f('x', 0.0), y0=f('y', 0.0),
                    realworld=int(float(d.get('r', 0) or 0)),
                    epsg=d.get('e'), grid=d.get('i'),
                    d_real=f('d'), d_paper=f('g'))

    @property
    def print_area(self):
        """(L,B,R,T) in map mm and print scale, from param string 1026."""
        p = self.param(1026)
        if not p: return None
        d = p[0]
        try:
            L, B, R, T = (float(d[k]) for k in 'LBRT')
        except (KeyError, ValueError):
            return None
        try: a = float(d.get('a', 0) or 0)
        except ValueError: a = 0.0
        return (L, B, R, T, a)

    # ---------- objects ----------
    def objects(self):
        """Yield dicts with sym, otp, and coordinate rings in map mm."""
        b = self.b
        off = self.obj_idx
        seen = set()
        while off and off not in seen and off < len(b):
            seen.add(off)
            nxt, = struct.unpack_from('<i', b, off)
            for i in range(256):
                p = off + 4 + i * 40
                if p + 40 > len(b): break
                pos, n, sym = struct.unpack_from('<iii', b, p + 16)
                otp, enc, status, vt = struct.unpack_from('<BBBB', b, p + 28)
                if pos <= 0 or status != 1: continue
                rc = struct.unpack_from('<iiii', b, p)
                yield self._read_obj(pos, sym, otp, rc)
            off = nxt if nxt > 0 else 0

    def _read_obj(self, pos, sym, otp, rc):
        b = self.b
        n_item, = struct.unpack_from('<I', b, pos + 44)
        co = pos + 56
        rings, cur = [], []
        for k in range(n_item):
            x, y = struct.unpack_from('<ii', b, co + k * 8)
            if (y & 2) and cur:          # first point of a hole
                rings.append(cur); cur = []
            cur.append(((x >> 8) / 100.0, (y >> 8) / 100.0))
        if cur: rings.append(cur)
        return dict(sym=sym, otp=otp, rings=rings,
                    rc=tuple((v >> 8) / 100.0 for v in rc))

    # ---------- helpers ----------
    def to_real(self, pts):
        """map mm -> real-world metres (easting, northing)."""
        s = self.setup
        f = s['scale'] / 1000.0
        a = math.radians(s['angle'])
        ca, sa = math.cos(a), math.sin(a)
        return [((x * f) * ca - (y * f) * sa + s['x0'],
                 (x * f) * sa + (y * f) * ca + s['y0']) for x, y in pts]
