#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["tzdata; sys_platform == 'win32'"]
# ///
"""Livelox for mange løypefiler om gangen: oversikt, opprydding og sending.

  python3 livelox_batch.py status <mappe> [--online]
  python3 livelox_batch.py adopt <løypefil> [--id <id>]
  python3 livelox_batch.py cleanup <mappe> [--yes] [--ids <id> ...]
  python3 livelox_batch.py run <plan.json> [--yes] [--verify]

status   viser hver løypefil med id og hva som er sendt eller importert, og
         sjekker at den har løyper, et georeferert kart og poster innenfor
         kartet. --online spør Livelox om importer gjort i nettleseren.
adopt    knytter en løypefil til en id som alt finnes i Livelox. Brukes når et
         arrangement er importert med en id fra før id-ordningen ble endret.
         Uten --id prøves de gamle formene (bare filnavnet, og
         aol-<mappe>-<filnavn>), og den som er importert, velges.
cleanup  sletter importerbare arrangementer som er sendt med de gamle
         id-formene og ikke importert. Importerte røres ikke, heller ikke
         id-er som en statusfil peker på. --ids legger til flere id-er.
run      sender det en plan beskriver. Verktøyet gjetter aldri dato eller
         klokkeslett; de må stå i planen:

           [{"ppen": "Herdla/Trening september 2026.ppen",
             "start": "2026-09-10T18:00", "end": "2026-09-10T20:00",
             "name": "Trening 10.09.2026"}]

         Stier er relative til planfila. Planen vises før noe sendes, og må
         bekreftes - eller kjøres med --yes.
"""
import argparse, json, os, sys, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import livelox_event as le
import state
from ppen import PurplePen
from ocad_geo import Georeference, map_extent


def find_ppen(folder, include_old=False):
    out = []
    for dirpath, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.')
                         and (include_old or d.lower() != 'old'))
        out += [os.path.join(dirpath, f) for f in sorted(files) if f.lower().endswith('.ppen')]
    return out


def quick_check(ppen):
    """Det samme build() stopper på, men uten å trenge dato og navn."""
    try:
        p = PurplePen(ppen)
    except Exception:
        return 'kan ikke leses'
    courses = [c for c in p.courses() if len(c['controls']) >= 2]
    if not courses:
        return 'ingen løyper'
    ocd = le.find_map_file(p, None)
    if not ocd:
        return 'kartet mangler'
    if not ocd.lower().endswith('.ocd'):
        return 'kartet er ikke OCAD'
    try:
        geo = Georeference(ocd)
    except Exception:
        return 'kartet kan ikke leses'
    if not geo.realworld:
        return 'kartet er ikke georeferert'
    ext = map_extent(geo.ocd)
    if ext:
        L, B, R, T = ext
        out = [x for c in courses for x in c['controls']
               if not (L <= x['x'] <= R and B <= x['y'] <= T)]
        if out:
            return '%d post%s utenfor kartet' % (len(out), 'er' if len(out) > 1 else '')
    return 'ok'


def describe(rec):
    if not rec:
        return 'ikke sendt'
    if rec.get('imported'):
        return 'importert (Livelox %s)' % rec.get('livelox_event_id', '?')
    if rec.get('livelox') == 'finnes ikke':
        return 'finnes ikke i Livelox'
    return 'sendt %s, ikke importert' % (rec.get('sent') or '?')[:10]


def cmd_status(a):
    files = find_ppen(a.folder, a.include_old)
    auth = le.get_auth() if a.online else None
    olds = {}
    for f in files:
        olds.setdefault(state.old_id(f), []).append(f)
    print('%-52s %-40s %-30s %s' % ('løypefil', 'id', 'Livelox', 'sjekk'))
    for f in files:
        rec = state.load(f)
        eid = rec.get('id') or state.new_id(f)
        if auth and rec:
            rec = le.refresh_state(f, eid, auth)
        note = quick_check(f)
        shared = len(olds[state.old_id(f)])
        if not rec and shared > 1:
            note += '  (gammel id delt av %d filer)' % shared
        print('%-52s %-40s %-30s %s' % (os.path.relpath(f, a.folder)[:52], eid[:40],
                                        describe(rec), note))
    print('\n%d løypefiler.' % len(files))


def lookup(eid, auth):
    st, r = le.request('GET', '%s/importableEvents/%s?includeImportedEvent=true'
                       % (le.API, urllib.parse.quote(eid)), auth)
    return r if st == 200 and isinstance(r, dict) else None


def cmd_adopt(a):
    rec = state.load(a.ppen)
    auth = le.get_auth()
    eid = a.id
    if not eid:
        found = [(i, lookup(i, auth)) for i in state.legacy_ids(a.ppen)]
        found = [(i, r) for i, r in found if r]
        found.sort(key=lambda x: not x[1].get('importedEvent'))
        if not found:
            sys.exit('Livelox kjenner ingen av de gamle id-ene (%s). Oppgi --id.'
                     % ', '.join(state.legacy_ids(a.ppen)))
        eid = found[0][0]
    if rec.get('id') and rec['id'] != eid and not a.force:
        sys.exit('%s er alt knyttet til %s. Bruk --force for å bytte.' % (a.ppen, rec['id']))
    state.save(a.ppen, dict(rec, id=eid))
    rec = le.refresh_state(a.ppen, eid, auth)
    print('%s -> %s: %s' % (os.path.basename(a.ppen), eid, describe(rec)))
    if rec.get('livelox') == 'finnes ikke':
        print('Advarsel: Livelox kjenner ikke denne id-en.')


def confirm(question, yes):
    if yes:
        return True
    if not sys.stdin.isatty():
        sys.exit('Trenger bekreftelse, men ingen terminal. Kjør med --yes når planen er sjekket.')
    return input(question + ' [j/N] ').strip().lower() in ('j', 'ja', 'y', 'yes')


def cmd_cleanup(a):
    files = find_ppen(a.folder, include_old=True)
    keep = {state.load(f).get('id') for f in files} - {None}
    cands = {i for f in files if not state.load(f) for i in state.legacy_ids(f)}
    cands = sorted((cands | set(a.ids or [])) - keep)
    auth = le.get_auth()
    delete, imported = [], []
    for oid in cands:
        r = lookup(oid, auth)
        if not r:
            continue
        (imported if r.get('importedEvent') else delete).append((oid, r.get('name', '')))
    for oid, name in imported:
        print('importert, ikke rørt: %-40s %s  (knytt til riktig fil med adopt)' % (oid, name))
    if not delete:
        print('Ingen gamle utkast å slette.')
        return
    print('Gamle utkast som ikke er importert:')
    for oid, name in delete:
        print('  %-40s %s' % (oid, name))
    if not confirm('Slette %d utkast i Livelox?' % len(delete), a.yes):
        print('Avbrutt.')
        return
    for oid, _ in delete:
        st, r = le.request('DELETE', '%s/importableEvents/%s' % (le.API, urllib.parse.quote(oid)), auth)
        print('  %s %s' % ('slettet' if st in (200, 204) else 'FEIL %s' % st, oid))


def cmd_run(a):
    base = os.path.dirname(os.path.abspath(a.plan))
    with open(a.plan, encoding='utf-8') as f:
        plan = json.load(f)
    auth = le.get_auth()
    rows = []
    for item in plan:
        ppen = os.path.join(base, item['ppen'])
        missing = [k for k in ('start', 'end') if not item.get(k)]
        if missing:
            rows.append((ppen, None, None, 'feil: mangler %s i planen' % ' og '.join(missing)))
            continue
        args = le.default_args(**{k: v for k, v in item.items() if k != 'ppen'}, ppen=ppen,
                               allow_outside=item.get('allow_outside', False))
        try:
            ev, files, geo, ocd = le.build(args)
        except SystemExit as e:
            rows.append((ppen, None, None, 'feil: %s' % str(e).splitlines()[0]))
            continue
        rec = le.refresh_state(ppen, ev['id'], auth) if state.load(ppen) else {}
        if rec.get('imported'):
            same = rec.get('event_sha256') == state.event_sha256(ev)
            action = 'uendret, hoppes over' if same else 'oppdateres (events/external)'
        elif rec.get('livelox') == 'sendt, ikke importert':
            action = 'sendes på nytt'
        else:
            action = 'opprettes'
        rows.append((ppen, ev, files, action))

    print('%-52s %-12s %s' % ('løypefil', 'dato', 'handling'))
    for ppen, ev, _, action in rows:
        print('%-52s %-12s %s' % (os.path.relpath(ppen, base)[:52],
                                  ev['timeInterval']['start'][:10] if ev else '', action))
    todo = [r for r in rows if r[1] and not r[3].startswith(('uendret', 'feil'))]
    if not todo:
        print('\nIngenting å sende.')
        return
    if not confirm('\nSende %d?' % len(todo), a.yes):
        print('Avbrutt.')
        return
    for ppen, ev, files, action in todo:
        print('\n=== %s' % os.path.relpath(ppen, base))
        r = le.send(ev, files, auth, ppen=ppen)
        if a.verify and state.load(ppen).get('livelox_event_id'):
            le.verify(ev, auth, state.load(ppen)['livelox_event_id'])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('status'); s.add_argument('folder')
    s.add_argument('--online', action='store_true'); s.add_argument('--include-old', action='store_true')
    s = sub.add_parser('adopt'); s.add_argument('ppen')
    s.add_argument('--id', help='uten --id prøves de gamle id-ene, og den importerte velges')
    s.add_argument('--force', action='store_true')
    s = sub.add_parser('cleanup'); s.add_argument('folder'); s.add_argument('--yes', action='store_true')
    s.add_argument('--ids', nargs='*', help='flere id-er å sjekke, f.eks. fra en tidligere kjøring')
    s = sub.add_parser('run'); s.add_argument('plan'); s.add_argument('--yes', action='store_true')
    s.add_argument('--verify', action='store_true')
    a = ap.parse_args()
    {'status': cmd_status, 'adopt': cmd_adopt, 'cleanup': cmd_cleanup, 'run': cmd_run}[a.cmd](a)


if __name__ == '__main__':
    main()
