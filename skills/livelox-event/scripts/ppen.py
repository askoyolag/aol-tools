"""Minimal reader for Purple Pen course files (.ppen).

A .ppen file is plain XML. Coordinates are given in millimetres in the map's
own paper coordinate system (same system as OCAD map mm, x right, y up),
so they can be converted to real-world coordinates with the georeferencing
of the OCAD background map (see ocad_geo.py).
"""
import math
import xml.etree.ElementTree as ET


class PurplePen:
    def __init__(self, path):
        self.path = path
        root = ET.parse(path).getroot()
        self.root = root
        ev = root.find('event')
        self.title = (ev.findtext('title') or '').strip()
        m = ev.find('map')
        self.map_kind = m.get('kind') if m is not None else None
        self.map_scale = float(m.get('scale')) if m is not None and m.get('scale') else None
        self.map_file = (m.text or '').strip() if m is not None else None
        self.map_path = m.get('absolute-path') if m is not None else None

        self.controls = {}
        for c in root.findall('control'):
            loc = c.find('location')
            self.controls[c.get('id')] = dict(
                id=c.get('id'),
                kind=c.get('kind'),                      # start | normal | finish | crossing-point ...
                code=(c.findtext('code') or '').strip() or None,
                x=float(loc.get('x')) if loc is not None else None,
                y=float(loc.get('y')) if loc is not None else None,
            )

        self.course_controls = {}
        for cc in root.findall('course-control'):
            nxt = cc.find('next')
            self.course_controls[cc.get('id')] = dict(
                id=cc.get('id'), control=cc.get('control'),
                next=nxt.get('course-control') if nxt is not None else None)

    def courses(self):
        """List of courses, each with an ordered list of control dicts."""
        out = []
        for c in self.root.findall('course'):
            first = c.find('first')
            opts = c.find('options')
            seq, seen = [], set()
            cur = first.get('course-control') if first is not None else None
            while cur and cur not in seen:
                seen.add(cur)
                cc = self.course_controls.get(cur)
                if not cc:
                    break
                ctrl = self.controls.get(cc['control'])
                if ctrl:
                    seq.append(ctrl)
                cur = cc['next']
            out.append(dict(
                id=c.get('id'),
                name=(c.findtext('name') or '').strip(),
                kind=c.get('kind', 'normal'),            # normal | score
                order=int(c.get('order') or 0),
                print_scale=float(opts.get('print-scale')) if opts is not None and opts.get('print-scale') else None,
                controls=seq,
                length=self.length(seq),
            ))
        out.sort(key=lambda d: d['order'])
        return out

    def length(self, seq):
        """Straight-line course length in metres (climb and route choice ignored)."""
        if not self.map_scale or len(seq) < 2:
            return None
        f = self.map_scale / 1000.0                      # map mm -> metres
        tot = 0.0
        for a, b in zip(seq, seq[1:]):
            tot += math.hypot(b['x'] - a['x'], b['y'] - a['y']) * f
        return round(tot)


if __name__ == '__main__':
    import sys, json
    p = PurplePen(sys.argv[1])
    print(json.dumps(dict(
        title=p.title, map=p.map_file, map_scale=p.map_scale, map_path=p.map_path,
        courses=[dict(name=c['name'], kind=c['kind'], length=c['length'],
                      controls=[(x['kind'], x['code']) for x in c['controls']])
                 for c in p.courses()]), ensure_ascii=False, indent=2))
