#!/usr/bin/env python3
"""Build (and optionally upload) a Livelox importable event from a Purple Pen file.

Reads a .ppen course file plus the georeferencing of its OCAD background map,
and produces the `importable event object` that the Livelox event integration
API expects (https://www.livelox.com/Documentation/Api/EventIntegration).

Without an API key it writes the JSON to disk so it can be inspected; with
LIVELOX_API_KEY set and --post it creates the importable event, uploads the
files, runs the validation endpoint and prints the URL where a logged-in
Livelox user finishes the import with one click.

  python3 livelox_event.py trening.ppen --start 2026-05-12T18:00 \
      --end 2026-05-12T21:00 --name "Tirsdagstrening" --club "Askøy OL"
"""
import argparse, datetime as dt, json, os, re, sys, urllib.error, urllib.parse, urllib.request, zoneinfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ppen import PurplePen
from ocad_geo import Georeference
import livelox_auth

API = os.environ.get('LIVELOX_API', 'https://api.livelox.com')
TYPE_MAP = {'start': 'Start', 'normal': 'Control', 'finish': 'Finish'}
WORLD_EXT = {'.png': '.pgw', '.tif': '.tfw', '.tiff': '.tfw', '.jpg': '.jgw', '.jpeg': '.jgw', '.gif': '.gfw'}


def slug(text):
    s = text.lower().replace('æ', 'ae').replace('ø', 'o').replace('å', 'a')
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', s)).strip('-')[:64]


def utc(local_iso, tz):
    naive = dt.datetime.fromisoformat(local_iso)
    aware = naive.replace(tzinfo=zoneinfo.ZoneInfo(tz))
    return aware.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def find_map_file(ppen, explicit):
    if explicit:
        return explicit
    base = os.path.dirname(os.path.abspath(ppen.path))
    if ppen.map_file:
        cand = os.path.join(base, ppen.map_file)
        if os.path.exists(cand):
            return cand
    names = [n for n in (ppen.map_file,
                         ppen.map_path.replace('\\', '/').split('/')[-1] if ppen.map_path else None) if n]
    for n in names:
        cand = os.path.join(base, n)
        if os.path.exists(cand):
            return cand
    # kartet kan ligge i en annen mappe i kartarkivet - let oppover og nedover
    root = base
    for _ in range(3):
        root = os.path.dirname(root)
        for dirpath, _dirs, fnames in os.walk(root):
            for n in names:
                if n in fnames:
                    return os.path.join(dirpath, n)
        if os.path.ismount(root) or root == os.path.dirname(root):
            break
    return None


def build(args):
    try:
        p = PurplePen(args.ppen)
    except Exception as e:
        sys.exit('Klarte ikke lese %s: %s' % (os.path.basename(args.ppen), e))
    ocd = find_map_file(p, args.ocd)
    if not ocd:
        sys.exit('Fant ikke kartfila som .ppen-fila peker på (%s). Bruk --ocd.'
                 % (p.map_file or 'ukjent'))
    if not ocd.lower().endswith('.ocd'):
        sys.exit('Purple Pen-prosjektet bruker %s som kart. Georeferering krever '
                 'OCAD-fila – oppgi den med --ocd, eller sett opp arrangementet '
                 'manuelt i Livelox.' % os.path.basename(ocd))
    geo = Georeference(ocd, args.epsg)
    if not geo.realworld:
        sys.exit('Kartet %s er ikke georeferert. Georeferer det i OCAD først.' % os.path.basename(ocd))
    if not geo.epsg:
        sys.exit('Kartet %s har koordinater, men oppgir ikke hvilket system. '
                 'Sett det i OCAD, eller bruk --epsg (25832/32632 for UTM 32N).'
                 % os.path.basename(ocd))

    controls, seen = [], {}
    for c in p.controls.values():
        t = TYPE_MAP.get(c['kind'])
        if not t:
            continue                       # crossing points, map exchanges etc.
        code = c['code'] or ('S' if t == 'Start' else 'F')
        if code in seen:
            continue
        seen[code] = True
        x, y = geo.to_projected(c['x'], c['y'])
        controls.append({'code': code, 'type': t,
                         'projectedPosition': {'x': round(x, 2), 'y': round(y, 2)}})

    courses = []
    for c in p.courses():
        seq = []
        for ctrl in c['controls']:
            t = TYPE_MAP.get(ctrl['kind'])
            if not t:
                continue
            seq.append({'code': ctrl['code'] or ('S' if t == 'Start' else 'F')})
        if len(seq) < 2:
            continue
        course = {'name': c['name'], 'controls': seq}
        if c['length']:
            course['length'] = c['length']
        courses.append(course)

    ev = {
        'id': args.id or slug(os.path.splitext(os.path.basename(args.ppen))[0]),
        'name': args.name or p.title,
        'timeInterval': {'start': utc(args.start, args.tz), 'end': utc(args.end, args.tz)},
        'timeZone': args.tz,
        'organisers': [{'name': args.club}],
        'country': args.country,
        'type': 'individual',
        'level': args.level,
        'projectionEpsgCode': geo.epsg,
        'controls': controls,
        'courses': courses,
    }

    files = {}
    mapfile = args.map or (None if args.no_map else ocd)
    if mapfile:
        m = {'fileName': os.path.basename(mapfile),
             'name': os.path.splitext(os.path.basename(ocd))[0],
             'mapScale': int(p.map_scale or geo.scale)}
        files[os.path.basename(mapfile)] = mapfile
        # OCD, OOM og KMZ bærer georefereringen selv; rasterkart trenger world-fil
        if os.path.splitext(mapfile)[1].lower() not in ('.ocd', '.oom', '.kmz'):
            world = args.world
            if not world:
                cand = os.path.splitext(mapfile)[0] + WORLD_EXT.get(os.path.splitext(mapfile)[1].lower(), '')
                world = cand if os.path.exists(cand) else None
            if world:
                m['georeference'] = {'worldFileName': os.path.basename(world)}
                files[os.path.basename(world)] = world
        ev['maps'] = [m]
    return ev, files, geo, ocd


def request(method, url, auth, data=None, ctype='application/json', retry=True):
    """auth er enten ('Bearer', token) eller ('ApiKey', key)."""
    req = urllib.request.Request(url, data=data, method=method)
    if auth[0] == 'Bearer':
        req.add_header('Authorization', 'Bearer ' + auth[1])
    else:
        req.add_header('ApiKey', auth[1])
    if data is not None:
        req.add_header('Content-Type', ctype)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read().decode('utf-8') or '{}'
            return r.status, (json.loads(body) if body.strip().startswith(('{', '[')) else body)
    except urllib.error.HTTPError as e:
        if e.code == 403 and auth[0] == 'Bearer' and retry:
            fresh = livelox_auth.refresh()        # utløpt token gir 403
            if fresh:
                return request(method, url, ('Bearer', fresh), data, ctype, retry=False)
        return e.code, e.read().decode('utf-8', 'replace')


def post(ev, files, auth):
    status, res = request('POST', API + '/importableEvents', auth,
                          json.dumps(ev).encode('utf-8'))
    if status != 200:
        sys.exit('POST /importableEvents feilet (%s): %s' % (status, res))
    eid = res['id']
    for name, path in files.items():
        with open(path, 'rb') as f:
            s, r = request('POST', '%s/importableEvents/%s/files/%s'
                           % (API, eid, urllib.parse.quote(name)), auth,
                           f.read(), 'application/octet-stream')
        print('  last opp %-34s %s  (%.1f MB)' % (name, s, os.path.getsize(path)/1e6))
    s, r = request('GET', '%s/importableEvents/%s/validationErrors' % (API, eid), auth)
    print('Validering:', json.dumps(r, ensure_ascii=False))
    print('\nÅpne denne i nettleseren og fullfør importen:\n  %s' % res.get('liveloxImportEventUrl'))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ppen')
    ap.add_argument('--start', required=True, help='lokal starttid, f.eks. 2026-05-12T18:00')
    ap.add_argument('--end', required=True, help='lokal sluttid')
    ap.add_argument('--name', help='arrangementsnavn (standard: tittelen i .ppen-fila)')
    ap.add_argument('--club', default='Askøy orienteringslag')
    ap.add_argument('--tz', default='Europe/Oslo')
    ap.add_argument('--country', default='NOR')
    ap.add_argument('--level', default='club', choices=['club', 'local', 'regional', 'national', 'international'])
    ap.add_argument('--ocd', help='kartfil, dersom .ppen ikke peker på en fil som finnes her')
    ap.add_argument('--map', help='annen kartfil enn OCAD-kartet .ppen-fila peker på (PNG/TIFF/JPEG/KMZ/OCD/OOM)')
    ap.add_argument('--no-map', action='store_true', help='ikke send kart - det finnes allerede i Livelox')
    ap.add_argument('--world', help='world-fil til kartbildet (.pgw/.tfw); finnes automatisk ved siden av bildet')
    ap.add_argument('--epsg', type=int, help='overstyr koordinatsystemet til kartet')
    ap.add_argument('--id', help='egen id for arrangementet (standard: filnavnet)')
    ap.add_argument('--out', default='.', help='hvor JSON-fila skrives')
    ap.add_argument('--post', action='store_true', help='last opp til Livelox (krever LIVELOX_API_KEY)')
    args = ap.parse_args()

    ev, files, geo, ocd = build(args)
    print('Kart:      %s  (1:%g, EPSG:%s, %.1f°)' % (os.path.basename(ocd), geo.scale, geo.epsg, geo.angle))
    print('Løyper:    %s' % ', '.join('%s (%s m)' % (c['name'], c.get('length', '?')) for c in ev['courses']))
    print('Poster:    %d' % len(ev['controls']))
    if 'maps' in ev:
        print('Kart:      sender %s' % ev['maps'][0]['fileName'])
    else:
        print('Kart:      ingen - forutsetter at kartet alt ligger i Livelox')

    out = os.path.join(args.out, 'livelox-%s.json' % ev['id'])
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(ev, f, ensure_ascii=False, indent=2)
    print('Skrev      %s' % out)

    if args.post:
        key = os.environ.get('LIVELOX_API_KEY')
        if key:
            auth = ('ApiKey', key)
        else:
            # innlogging krever et menneske foran skjermen; ellers feil med en gang
            interactive = sys.stdin.isatty() and not os.environ.get('LIVELOX_NO_BROWSER')
            auth = ('Bearer', livelox_auth.access_token(interactive=interactive))
        if not auth[1]:
            sys.exit('Ingen tilgang til Livelox. Kjør livelox_auth.py for å logge inn.')
        post(ev, files, auth)


if __name__ == '__main__':
    main()
