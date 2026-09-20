# -*- coding: utf-8 -*-
"""Areal av det trykte kartet: ramme minus blending (white-out)."""
import struct, math, re, numpy as np
from PIL import Image, ImageDraw
from ocad import OcadFile

WHITE_RE = re.compile(r'(white|hvit|blend)', re.I)
FRAME_RE = re.compile(r'^\s*ramme\s*$', re.I)

def symbol_table(o):
    b, off, out, seen = o.b, o.sym_idx, {}, set()
    while off and off < len(b) and off not in seen:
        seen.add(off)
        nxt, = struct.unpack_from('<I', b, off)
        for i in range(256):
            pos, = struct.unpack_from('<i', b, off + 4 + i*4)
            if pos <= 0: continue
            size, symnum = struct.unpack_from('<ii', b, pos)
            otp, flags, sel, status = struct.unpack_from('<BBBB', b, pos + 8)
            nc, = struct.unpack_from('<h', b, pos + 26)
            cols = struct.unpack_from('<14h', b, pos + 28)
            desc = b[pos+56:pos+120].decode('utf-16-le', 'replace').split('\x00', 1)[0]
            out[symnum] = dict(otp=otp, status=status, colors=list(cols[:max(1, nc)]), desc=desc)
        off = nxt
    return out

def color_names(o):
    names = {}
    for rt, oi, s in o.strings:
        if rt != 9: continue
        p = s.split('\t'); d = {x[0]: x[1:] for x in p[1:] if x}
        try: names[int(float(d.get('n', '-1')))] = p[0]
        except ValueError: pass
    return names

LAYOUT_MAX = 10000      # symbol numbers below this are layout/design symbols,
                        # map symbols are >= 100000 (101.0 = 101000 ...)

def is_white(sym, syms, cnames):
    """True only for layout white-out symbols - never for map symbols such as
    'Skog, typisk for omraadet' whose colour is called 'Hvit i gul'."""
    if sym >= LAYOUT_MAX: return False
    info = syms.get(sym)
    if not info or not info['colors']: return False
    return any(WHITE_RE.search(cnames.get(c, '')) for c in info['colors'])

def to_real(o, pts):
    s = o.setup; f = s['scale']/1000.0
    a = math.radians(s['angle']); ca, sa = math.cos(a), math.sin(a)
    return [((x*f)*ca - (y*f)*sa + s['x0'], (x*f)*sa + (y*f)*ca + s['y0']) for x, y in pts]

def find_frame(o):
    """-> (corners in real-world m, kilde)"""
    syms, cn = symbol_table(o), color_names(o)
    named, rects, graph = [], [], []
    for ob in o.objects():
        if not ob['rings'] or len(ob['rings'][0]) < 3: continue
        r = ob['rings'][0]
        info = syms.get(ob['sym'])
        w = max(p[0] for p in r) - min(p[0] for p in r)
        h = max(p[1] for p in r) - min(p[1] for p in r)
        f = o.setup['scale']/1000.0
        if w*f < 20 or h*f < 20: continue
        if info and FRAME_RE.match(info['desc'] or ''):   named.append((w*h, r))
        elif ob['otp'] == 7:                               rects.append((w*h, r))
        elif ob['sym'] < 0 and ob['otp'] == 2:             graph.append((w*h, r))
    if named:
        return to_real(o, max(named)[1]), 'rammeobjekt «Ramme»'
    pa = o.print_area
    if pa and abs(pa[2]-pa[0]) > 0 and abs(pa[3]-pa[1]) > 0 and pa[4]:
        L, B, R, T = pa[:4]
        f = o.setup['scale']/1000.0
        pw = abs(R-L)*f*1000.0/pa[4]; ph = abs(T-B)*f*1000.0/pa[4]
        if 80 < pw < 1300 and 80 < ph < 1300:        # plausible paper size in mm
            return to_real(o, [(L, B), (R, B), (R, T), (L, T)]), 'utskriftsparameter (1026)'
    for cand, kilde in ((rects, 'rektangelobjekt'), (graph, 'grafisk ramme')):
        if cand:
            return to_real(o, max(cand)[1]), kilde
    return None, None

def blend_rings(o):
    """White-out area objects, as lists of rings in real-world metres."""
    syms, cn = symbol_table(o), color_names(o)
    out = []
    for ob in o.objects():
        if ob['otp'] != 3: continue
        if not is_white(ob['sym'], syms, cn): continue
        out.append([to_real(o, r) for r in ob['rings'] if len(r) >= 3])
    return [r for r in out if r]

def printed_area(design_path, map_path=None, cell_target=1600):
    o = OcadFile(design_path)
    frame, kilde = find_frame(o)
    if not frame: return None
    xs = [p[0] for p in frame]; ys = [p[1] for p in frame]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    W, H = maxx-minx, maxy-miny
    cell = max(0.15, max(W, H)/cell_target)
    nx, ny = int(W/cell)+3, int(H/cell)+3
    img = Image.new('1', (nx, ny), 0); d = ImageDraw.Draw(img)
    px = lambda ring: [(int((x-minx)/cell)+1, ny-2-int((y-miny)/cell)) for x, y in ring]
    d.polygon(px(frame), fill=1, outline=1)
    frame_px = np.array(img, dtype=bool).sum()
    sources = [o] + ([OcadFile(map_path)] if map_path and map_path != design_path else [])
    n_blend = 0
    for src in sources:
        for rings in blend_rings(src):
            for j, r in enumerate(rings):
                d.polygon(px(r), fill=0 if j else 0, outline=0) if False else None
            d.polygon(px(rings[0]), fill=0, outline=0)
            for r in rings[1:]:            # holes in the white-out show the map again
                d.polygon(px(r), fill=1, outline=1)
            n_blend += 1
    arr = np.array(img, dtype=bool)
    # how much of the printed sheet actually carries map content
    cov = None
    if map_path:
        from scipy import ndimage
        mo = OcadFile(map_path)
        mimg = Image.new('1', (nx, ny), 0); md = ImageDraw.Draw(mimg)
        for ob in mo.objects():
            if ob['otp'] not in (1, 2, 3): continue
            for r in ob['rings']:
                q = px(to_real(mo, r))
                if not any(-50 <= a <= nx+50 and -50 <= b <= ny+50 for a, b in q): continue
                if ob['otp'] == 3 and len(q) >= 3: md.polygon(q, fill=1, outline=1)
                elif len(q) >= 2: md.line(q, fill=1, width=1)
        marr = np.array(mimg, dtype=bool)
        rr = 25.0/cell
        closed = ndimage.distance_transform_edt(~marr) <= rr
        p = int(np.ceil(rr))+2
        closed = (ndimage.distance_transform_edt(
            np.pad(closed, p, constant_values=True)) > rr)[p:-p, p:-p] & closed
        cov = float((closed & arr).sum())
    # exact frame geometry via the minimum rotated rectangle
    from shapely.geometry import Polygon
    poly = Polygon(frame)
    mrr = poly.minimum_rotated_rectangle
    c = list(mrr.exterior.coords)
    side1, side2 = math.dist(c[0], c[1]), math.dist(c[1], c[2])
    frame_area = poly.area
    vis = frame_area * (float(arr.sum())/float(frame_px)) if frame_px else 0.0
    return dict(frame_m=(max(side1, side2), min(side1, side2)), frame_area_m2=frame_area,
                frame_px_m2=float(frame_px)*cell*cell,
                printed_area_m2=vis,
                blended_m2=frame_area - vis,
                content_area_m2=(frame_area*(cov/float(frame_px)) if cov is not None and frame_px else None),
                n_blend=n_blend, cell_m=cell, kilde=kilde,
                centre=(float(np.mean(xs)), float(np.mean(ys))))
