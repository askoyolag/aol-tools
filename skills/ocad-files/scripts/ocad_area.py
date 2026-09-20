"""Estimate the mapped area of an OCAD map (raster morphology via distance transform)."""
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from ocad import OcadFile

GEOM_TYPES = (1, 2, 3)          # point, line, area  (text/rectangle excluded)

def _dilate(mask, r):
    if r <= 0: return mask
    return ndimage.distance_transform_edt(~mask) <= r

def _erode(mask, r, border_full=True):
    if r <= 0: return mask
    p = int(np.ceil(r)) + 2
    m = np.pad(mask, p, constant_values=bool(border_full))
    out = ndimage.distance_transform_edt(m) > r
    return out[p:-p, p:-p]

def rasterize(o, max_cells=2200):
    """-> (bool array, cell size in m, (minx,miny) in m, n_objects)"""
    f = o.setup['scale'] / 1000.0
    objs = [ob for ob in o.objects() if ob['otp'] in GEOM_TYPES and ob['rings']]
    if not objs or not f: return None, None, None, len(objs)
    xs = np.fromiter((p[0] for ob in objs for r in ob['rings'] for p in r), float)
    ys = np.fromiter((p[1] for ob in objs for r in ob['rings'] for p in r), float)
    minx, maxx, miny, maxy = xs.min()*f, xs.max()*f, ys.min()*f, ys.max()*f
    W, H = maxx-minx, maxy-miny
    cell = max(0.5, max(W, H)/max_cells)
    nx, ny = int(W/cell)+3, int(H/cell)+3
    img = Image.new('1', (nx, ny), 0); d = ImageDraw.Draw(img)
    for ob in objs:
        for ring in ob['rings']:
            pts = [(int((x*f-minx)/cell)+1, ny-2-int((y*f-miny)/cell)) for x, y in ring]
            if ob['otp'] == 3 and len(pts) >= 3: d.polygon(pts, fill=1, outline=1)
            elif len(pts) >= 2: d.line(pts, fill=1, width=1)
            else: d.point(pts, fill=1)
    return np.array(img, dtype=bool), cell, (minx, miny, maxx, maxy), len(objs)

def analyse(path, close_m=25.0, stray_m=15.0, max_cells=2200, min_frac=0.03, max_clusters=6):
    o = OcadFile(path)
    s = o.setup
    scale = s['scale']
    f = scale/1000.0
    res = dict(path=path, scale=scale, epsg=s['epsg'], angle=s['angle'],
               x0=s['x0'], y0=s['y0'], realworld=s['realworld'])
    pa = o.print_area
    if pa:
        L, B, R, T, a = pa
        res.update(print_w_m=(R-L)*f, print_h_m=(T-B)*f,
                   print_area_m2=abs((R-L)*(T-B))*f*f, print_scale=a,
                   print_paper_mm=((R-L)*scale/a if a else None, (T-B)*scale/a if a else None),
                   print_rect_mm=(L, B, R, T))
    arr, cell, ext, n_obj = rasterize(o, max_cells)
    res['n_obj'] = n_obj
    if arr is None: return res
    minx, miny, maxx, maxy = ext
    ny, nx = arr.shape
    res['full_bbox_m'] = (maxx-minx, maxy-miny)
    res['full_bbox_area_m2'] = (maxx-minx)*(maxy-miny)
    res['cell_m'] = cell
    R = close_m/cell
    dil = _dilate(arr, R)
    lab, n = ndimage.label(dil)
    if n == 0: return res
    sizes = ndimage.sum(dil, lab, range(1, n+1))
    total = sizes.sum()
    clusters = []
    for ci in np.argsort(sizes)[::-1]:
        if clusters and sizes[ci] < min_frac*total: break
        m = (lab == ci+1)
        closed = _erode(m, R) & m
        area = closed.sum()*cell*cell
        core = _dilate(_erode(closed, stray_m/cell, border_full=False), stray_m/cell) & closed
        l2, n2 = ndimage.label(core)
        if n2:
            sz = ndimage.sum(core, l2, range(1, n2+1))
            core = (l2 == int(np.argmax(sz))+1)
        else:
            core = closed
        yy, xx = np.nonzero(core)
        bw = (xx.max()-xx.min()+1)*cell; bh = (yy.max()-yy.min()+1)*cell
        clusters.append(dict(area_m2=float(area), bbox_m=(float(bw), float(bh)),
                             bbox_area_m2=float(bw*bh), core_area_m2=float(core.sum()*cell*cell),
                             cx=float(minx+xx.mean()*cell), cy=float(miny+(ny-2-yy.mean())*cell),
                             share=float(sizes[ci]/total)))
        if len(clusters) >= max_clusters: break
    res['clusters'] = clusters
    res['n_clusters'] = len(clusters)
    res['main_area_m2'] = clusters[0]['area_m2']
    res['main_bbox_m'] = clusters[0]['bbox_m']
    res['main_bbox_area_m2'] = clusters[0]['bbox_area_m2']
    return res
