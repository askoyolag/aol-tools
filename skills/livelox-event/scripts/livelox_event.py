#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["tzdata; sys_platform == 'win32'"]
# ///
"""Build (and optionally upload) a Livelox importable event from a Purple Pen file.

Reads a .ppen course file plus the georeferencing of its OCAD background map,
and produces the `importable event object` that the Livelox event integration
API expects (https://www.livelox.com/Documentation/Api/EventIntegration).

Without --post it writes the JSON and an IOF XML file to disk, so the courses
can be checked - or uploaded by hand in Livelox. With --post it logs in
(livelox_auth.py), creates the importable event, uploads the files, runs the
validation endpoint and prints the URL where the course setter finishes the
import with one click.

  python3 livelox_event.py trening.ppen --start 2026-05-12T18:00 \
      --end 2026-05-12T21:00 --name "Tirsdagstrening" --club "Askøy OL"
"""
import argparse, datetime as dt, json, math, os, re, sys, urllib.error, urllib.parse, urllib.request, zoneinfo
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ppen import PurplePen
from ocad_geo import Georeference, utm_to_wgs84, map_extent
import iof_xml
import livelox_auth
import state

API = os.environ.get('LIVELOX_API', 'https://api.livelox.com')
TYPE_MAP = {'start': 'Start', 'normal': 'Control', 'finish': 'Finish'}
WORLD_EXT = {'.png': '.pgw', '.tif': '.tfw', '.tiff': '.tfw', '.jpg': '.jgw', '.jpeg': '.jgw', '.gif': '.gfw'}


def slug(text):
    s = text.lower().replace('æ', 'ae').replace('ø', 'o').replace('å', 'a')
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', s)).strip('-')[:64]


# Normaltid (timer fra UTC) for europeiske soner som følger EUs sommertid.
# Brukes bare når Python mangler tidssonedatabasen - som på Windows uten
# pakken tzdata.
EU_SONER = {'Europe/London': 0, 'Europe/Dublin': 0, 'Europe/Lisbon': 0,
            'Europe/Oslo': 1, 'Europe/Stockholm': 1, 'Europe/Copenhagen': 1,
            'Europe/Berlin': 1, 'Europe/Amsterdam': 1, 'Europe/Brussels': 1,
            'Europe/Paris': 1, 'Europe/Zurich': 1, 'Europe/Vienna': 1,
            'Europe/Prague': 1, 'Europe/Warsaw': 1, 'Europe/Rome': 1,
            'Europe/Madrid': 1, 'Europe/Budapest': 1,
            'Europe/Helsinki': 2, 'Europe/Tallinn': 2, 'Europe/Riga': 2,
            'Europe/Vilnius': 2}


def _siste_sondag(aar, mnd):
    d = dt.date(aar, mnd + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def _eu_utc(naive, tz):
    """Lokal tid -> UTC etter EUs regel: sommertid fra kl. 01 UTC siste søndag
    i mars til kl. 01 UTC siste søndag i oktober."""
    std = dt.timedelta(hours=EU_SONER[tz])
    start = dt.datetime.combine(_siste_sondag(naive.year, 3), dt.time(1))
    slutt = dt.datetime.combine(_siste_sondag(naive.year, 10), dt.time(1))
    sommer = start <= naive - std <= slutt
    return naive - std - (dt.timedelta(hours=1) if sommer else dt.timedelta(0))


def utc(local_iso, tz):
    naive = dt.datetime.fromisoformat(local_iso)
    try:
        aware = naive.replace(tzinfo=zoneinfo.ZoneInfo(tz))
        return aware.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except zoneinfo.ZoneInfoNotFoundError:
        if tz not in EU_SONER:
            sys.exit('Python mangler tidssonedata for %s. Installer den med '
                     '«pip install tzdata», eller kjør skriptet med uv run.' % tz)
        return _eu_utc(naive, tz).strftime('%Y-%m-%dT%H:%M:%SZ')


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
    # kartet kan ligge i en annen mappe i kartarkivet - let oppover og nedover.
    # Søket er begrenset: en umettelig os.walk fra hjemmemappa er ikke noe å
    # utsette en løypelegger for.
    root, seen = base, 0
    for _ in range(3):
        root = os.path.dirname(root)
        for dirpath, dirs, fnames in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            seen += 1
            if seen > 5000:
                return None
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

    if not courses:
        sys.exit('%s har ingen løyper med minst start og mål - ingenting å sende.'
                 % os.path.basename(args.ppen))

    # Poster utenfor kartet betyr nesten alltid feil georeferering eller feil
    # kart, og Livelox avviser dem først etter opplastingen. Sjekk før.
    extent = map_extent(geo.ocd)
    if extent:
        L, B, R, T = extent
        used = {cc['code'] for c in courses for cc in c['controls']}
        outside = []
        for c in p.controls.values():
            t = TYPE_MAP.get(c['kind'])
            code = c['code'] or ('S' if t == 'Start' else 'F') if t else None
            if code in used and not (L <= c['x'] <= R and B <= c['y'] <= T):
                dx = max(L - c['x'], 0, c['x'] - R); dy = max(B - c['y'], 0, c['y'] - T)
                outside.append((code, math.hypot(dx, dy) * geo.scale / 1000.0))
        if outside and not getattr(args, 'allow_outside', False):
            sys.exit('Poster utenfor kartet %s:\n%s\nSjekk at løypefila hører til '
                     'dette kartet. Bruk --allow-outside for å sende likevel.'
                     % (os.path.basename(ocd), '\n'.join('  %-4s %6.0f m utenfor' % o
                                                        for o in sorted(outside))))

    ev = {
        'id': state.event_id(args.ppen, args.id),
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


def fail(what, status, body):
    """Avslutter med en melding som skiller manglende tilgang fra andre feil."""
    if status == 403:
        sys.exit('%s: Livelox svarte 403 Forbidden.\n'
                 'Tokenet er gyldig og har scope events.import, så dette er ikke\n'
                 'en utløpt innlogging: klienten eller kontoen mangler tilgang til\n'
                 'importerbare arrangementer, og det må Livelox slå på.\n'
                 'Inntil da: kjør uten --post og last opp IOF XML-fila manuelt\n'
                 'under Løyper i Livelox.' % what)
    sys.exit('%s feilet (%s): %s' % (what, status, body))


def upload(eid, files, auth):
    for name, path in files.items():
        with open(path, 'rb') as f:
            data = f.read()
        st, r = request('POST', '%s/importableEvents/%s/files/%s'
                        % (API, eid, urllib.parse.quote(name)), auth,
                        data, 'application/octet-stream')
        if st not in (200, 201):
            fail('Opplasting av %s' % name, st, r)
        print('  lastet opp %-32s %.1f MB' % (name, len(data)/1e6))


def validate(eid, auth):
    """Stopper før brukeren sendes videre dersom Livelox har innvendinger."""
    st, r = request('GET', '%s/importableEvents/%s/validationErrors' % (API, eid), auth)
    if st != 200 or not isinstance(r, dict):
        print('Kunne ikke validere (%s) - fortsetter.' % st)
        return
    for w in r.get('warnings') or []:
        print('  advarsel: %s' % w)
    errors = r.get('errors') or []
    if errors:
        print('\nLivelox godtar ikke arrangementet:')
        for e in errors:
            print('  - %s' % e)
        sys.exit('Rett opp dette og kjør på nytt.')


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def send(ev, files, auth, ppen=None):
    """Oppretter arrangementet, eller oppdaterer det som allerede finnes.

    Bare publiserte endepunkter brukes. Et arrangement som alt er importert i
    Livelox oppdateres med PUT /events/external/{id}, slik Livelox anbefaler -
    uten omvei om nettleseren. Ellers sendes det importerbare arrangementet
    (på nytt) med POST /importableEvents; Livelox gjenbruker id-en vi oppgir,
    så det blir aldri dubletter. Med ppen oppdateres statusfila ved siden av.
    """
    eid = str(ev['id'])
    qid = urllib.parse.quote(eid)
    st0 = state.load(ppen) if ppen else {}
    rec = dict(st0, id=eid, name=ev['name'], start=ev['timeInterval']['start'],
               end=ev['timeInterval']['end'], event_sha256=state.event_sha256(ev))
    st, existing = request('GET', '%s/importableEvents/%s?includeImportedEvent=true'
                           % (API, qid), auth)
    known = st == 200 and isinstance(existing, dict)
    imported = bool(known and existing.get('importedEvent'))

    if imported:
        lid = existing['importedEvent'].get('id')
        show = (existing.get('link') or {}).get('liveloxShowEventUrl') or ''
        st, r = request('PUT', '%s/events/external/%s' % (API, qid), auth,
                        json.dumps(ev).encode('utf-8'))
        if st != 200:
            fail('Oppdatering av arrangementet', st, r)
        if ppen:
            state.save(ppen, dict(rec, imported=True, livelox_event_id=lid,
                                  show_url=show or rec.get('show_url'), sent=_now()))
        print('\nOppdateringen er sendt til Livelox%s.'
              % (' (operasjon %s)' % r.get('operationId') if isinstance(r, dict) and r.get('operationId') else ''))
        if show:
            print('  %s' % show)
        print('Livelox behandler den i bakgrunnen, vanligvis i løpet av sekunder.\n'
              'Ifølge dokumentasjonen oppdateres bare navn og klasser denne veien -\n'
              'kontroller løypene (--verify, eller i Livelox).')
        return dict(r if isinstance(r, dict) else {}, livelox_event_id=lid)

    if known:
        print('Arrangementet er sendt før, men ikke importert ennå - sender oppdatert versjon.')
    st, r = request('POST', API + '/importableEvents', auth, json.dumps(ev).encode('utf-8'))
    if st != 200:
        fail('Oppretting av arrangementet', st, r)
    eid = str(r.get('id', eid))

    upload(eid, files, auth)
    validate(eid, auth)

    url = (r.get('liveloxImportEventUrl')
           or (r.get('link') or {}).get('liveloxImportEventUrl'))
    if ppen:
        maps = [f for f in files.values() if f.lower().endswith(('.ocd', '.oom', '.kmz', '.png', '.tif', '.tiff', '.jpg', '.jpeg', '.gif'))]
        state.save(ppen, dict(rec, id=eid, imported=False, import_url=url, sent=_now(),
                              map_file=os.path.basename(maps[0]) if maps else None,
                              map_sha256=state.file_sha256(maps[0]) if maps else None))
    print('\nÅpne denne i nettleseren og fullfør importen:\n  %s' % (url or '(ingen URL i svaret)'))
    print('(Lenken endres hver gang arrangementet sendes på nytt - bruk den siste.)')
    return r


def _dist_m(a, b):
    """Avstand i meter mellom to (lengdegrad, breddegrad); godt nok på noen km."""
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * 111320 * math.cos(lat), (a[1] - b[1]) * 110540)


def verify(ev, auth, livelox_event_id, tol_m=5.0):
    """Leser løypene tilbake fra Livelox og sammenligner med det som ble sendt.

    Bruker GET /orienteering/courses/iofxml, som krever scopet courses.read og
    bare returnerer det som er publisert. Returnerer en liste med avvik, eller
    None når tilbakelesingen ikke var mulig.
    """
    st, r = request('GET', '%s/orienteering/courses/iofxml?eventId=%s&includeControls=true'
                    % (API, livelox_event_id), auth)
    if st in (401, 403):
        print('Kan ikke lese løypene tilbake: CourseImport mangler scopet courses.read\n'
              '(eller arrangementet er ikke publisert ennå).')
        return None
    if st != 200 or not isinstance(r, str) or '<' not in r:
        print('Kan ikke lese løypene tilbake (%s).' % st)
        return None
    ns = {'i': 'http://www.orienteering.org/datastandard/3.0'}
    root = ET.fromstring(r)
    got_pos = {}
    for c in root.iter('{%s}Control' % ns['i']):
        cid, pos = c.find('i:Id', ns), c.find('i:Position', ns)
        if cid is not None and pos is not None:
            got_pos[cid.text] = (float(pos.get('lng')), float(pos.get('lat')))
    got_courses = {}
    for c in root.iter('{%s}Course' % ns['i']):
        n = c.find('i:Name', ns)
        if n is not None:
            got_courses[n.text] = [cc.find('i:Control', ns).text
                                   for cc in c.findall('i:CourseControl', ns)]
    if not got_courses:
        print('Livelox returnerte ingen løyper - trolig er de ikke publisert ennå.')
        return None

    want = {c['name']: [x['code'] for x in c['controls']] for c in ev['courses']}
    diffs = []
    for name in sorted(set(want) | set(got_courses)):
        if name not in got_courses:
            diffs.append('løype %s finnes ikke i Livelox' % name)
        elif name not in want:
            diffs.append('løype %s finnes i Livelox, men ikke i løypefila' % name)
        elif want[name] != got_courses[name]:
            diffs.append('løype %s: Livelox har %s, løypefila %s'
                         % (name, '-'.join(got_courses[name]), '-'.join(want[name])))
    for c in ev['controls']:
        mine = utm_to_wgs84(c['projectedPosition']['x'], c['projectedPosition']['y'],
                            ev['projectionEpsgCode'])
        theirs = got_pos.get(c['code'])
        if mine and theirs and _dist_m(mine, theirs) > tol_m:
            diffs.append('post %s ligger %.0f m fra løypefila' % (c['code'], _dist_m(mine, theirs)))
    print('Kontroll mot Livelox: %s' % ('alt stemmer' if not diffs else '%d avvik' % len(diffs)))
    for d in diffs:
        print('  - ' + d)
    return diffs


def refresh_state(ppen, eid, auth):
    """Spør Livelox om arrangementet er importert, og skriv det i statusfila.
    Fanger opp importer som er fullført i nettleseren etter forrige sending."""
    rec = state.load(ppen)
    st, r = request('GET', '%s/importableEvents/%s?includeImportedEvent=true'
                    % (API, urllib.parse.quote(str(eid))), auth)
    if st == 404:
        return dict(rec, livelox='finnes ikke')
    if st != 200 or not isinstance(r, dict):
        return dict(rec, livelox='ukjent (%s)' % st)
    imp = r.get('importedEvent')
    link = r.get('link') or {}
    if rec or imp:                       # skriv bare om det er noe å huske
        rec = state.save(ppen, dict(rec, id=str(eid), imported=bool(imp),
                                    livelox_event_id=(imp or {}).get('id', rec.get('livelox_event_id')),
                                    show_url=link.get('liveloxShowEventUrl', rec.get('show_url')),
                                    import_url=link.get('liveloxImportEventUrl', rec.get('import_url'))))
    return dict(rec, livelox='importert' if imp else 'sendt, ikke importert')


def get_auth():
    key = os.environ.get('LIVELOX_API_KEY')
    if key:
        return ('ApiKey', key)
    # innlogging krever et menneske foran skjermen; ellers feil med en gang
    interactive = sys.stdin.isatty() and not os.environ.get('LIVELOX_NO_BROWSER')
    tok = livelox_auth.access_token(interactive=interactive)
    if not tok:
        sys.exit('Ingen tilgang til Livelox. Kjør livelox_auth.py for å logge inn.')
    return ('Bearer', tok)


def default_args(**kw):
    """Argumentene build() forventer, med samme standardverdier som kommandolinjen.
    Brukes av livelox_batch.py."""
    d = dict(ppen=None, start=None, end=None, name=None, club='Askøy orienteringslag',
             tz='Europe/Oslo', country='NOR', level='club', ocd=None, map=None,
             no_map=False, world=None, epsg=None, id=None, out='.', post=False,
             allow_outside=False, verify=False)
    d.update(kw)
    return argparse.Namespace(**d)


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
    ap.add_argument('--id', help='egen id (standard: fra statusfila, ellers mappe + filnavn)')
    ap.add_argument('--allow-outside', action='store_true',
                    help='send selv om poster ligger utenfor kartet')
    ap.add_argument('--verify', action='store_true',
                    help='les løypene tilbake fra Livelox etterpå (krever scopet courses.read)')
    ap.add_argument('--out', default='.', help='mappe der JSON- og IOF XML-fila skrives (lages om den mangler)')
    ap.add_argument('--post', action='store_true',
                    help='last opp til Livelox (krever innlogging, se livelox_auth.py)')
    args = ap.parse_args()

    ev, files, geo, ocd = build(args)
    print('Kart:      %s  (1:%g, EPSG:%s, %.1f°)' % (os.path.basename(ocd), geo.scale, geo.epsg, geo.angle))
    print('Løyper:    %s' % ', '.join('%s (%s m)' % (c['name'], c.get('length', '?')) for c in ev['courses']))
    print('Poster:    %d' % len(ev['controls']))
    if 'maps' in ev:
        print('Kart:      sender %s' % ev['maps'][0]['fileName'])
    else:
        print('Kart:      ingen - forutsetter at kartet alt ligger i Livelox')

    os.makedirs(args.out, exist_ok=True)
    out = os.path.join(args.out, 'livelox-%s.json' % ev['id'])
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(ev, f, ensure_ascii=False, indent=2)
    print('Skrev      %s' % out)

    # IOF XML med ekte koordinater: Livelox' nettside plasserer ikke .ppen selv,
    # så dette er fila som skal lastes opp under Løyper ved manuelt oppsett.
    lonlat = {c['code']: utm_to_wgs84(c['projectedPosition']['x'],
                                      c['projectedPosition']['y'], ev['projectionEpsgCode'])
              for c in ev['controls']}
    if all(lonlat.values()):
        xml = os.path.join(args.out, 'livelox-%s.xml' % ev['id'])
        with open(xml, 'w', encoding='utf-8') as f:
            f.write(iof_xml.course_data(ev, lonlat))
        print('Skrev      %s  (IOF XML 3.0 - last opp denne under Løyper i Livelox)' % xml)
    else:
        print('IOF XML:   hoppet over - EPSG:%s er ikke UTM' % ev['projectionEpsgCode'])

    print('Id:        %s%s' % (ev['id'], '  (fra statusfila)' if state.load(args.ppen).get('id') == ev['id'] else ''))

    if args.post or args.verify:
        auth = get_auth()
    if args.post:
        r = send(ev, files, auth, ppen=args.ppen)
    if args.verify:
        lid = (state.load(args.ppen).get('livelox_event_id')
               or refresh_state(args.ppen, ev['id'], auth).get('livelox_event_id'))
        if not lid:
            print('Kan ikke kontrollere: arrangementet er ikke importert i Livelox ennå.')
        else:
            verify(ev, auth, lid)

    if args.level in ('club', 'local'):
        print('\nHusk:      publiseringstiden settes i Livelox, ikke via API-et. På treninger\n'
              '           skal den være når arrangementet starter (første start), ikke når\n'
              '           siste deltaker starter - se Tilgangsbegrensning.')


if __name__ == '__main__':
    main()
