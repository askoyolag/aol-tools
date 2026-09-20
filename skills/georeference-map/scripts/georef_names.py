#!/usr/bin/env python3
"""Georeferer et OCAD-kart ved hjelp av stedsnavnene som står på kartet.

Kartet har allerede fasiten i seg: navn som «Skråmestøvatnet» og «Ådlandsvik»
står med koordinater i kartets eget system, og Kartverkets stedsnavn-API gir
de samme navnene i ekte koordinater. To navn er nok til å bestemme rotasjon og
origo; resten brukes til å kontrollere at treffet stemmer.

  python3 georef_names.py kart.ocd --kommune Askøy

Skriptet skriver ingenting i kartfila – det gir tallene du taster inn i OCAD
under «Kart > Velg målestokk og referansesystem».
"""
import argparse, json, math, os, re, sys, time, urllib.parse, urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, '..', '..', 'ocad-files', 'scripts'))
from ocad import OcadFile                                    # noqa: E402
from georef_osm import ll2utm, utm_zone, apply, refine       # noqa: E402

API = 'https://api.kartverket.no/stedsnavn/v1/navn'
UA = 'aol-tools georef (orienteringskart)'
JUNK = re.compile(r'[0-9,:;/()]|^(nord|sør|øst|vest)$', re.I)


def map_names(path, min_len=4):
    """Tekstobjekter i kartet, i lokale meter. Navn delt over to linjer
    («Skråmestø-» / «vatnet») settes sammen igjen."""
    o = OcadFile(path)
    f = (o.setup['scale'] or 10000.0) / 1000.0
    raw = []
    for ob in o.objects():
        t = (ob['text'] or '').strip()
        if not t or not ob['rings'] or not ob['rings'][0]:
            continue
        x, y = ob['rings'][0][0]
        raw.append([t, x * f, y * f])
    out, used = [], set()
    for i, (t, x, y) in enumerate(raw):
        if i in used or JUNK.search(t) or len(t) < min_len:
            continue
        if t.endswith('-'):                       # navn delt over to linjer
            best, bd = None, 400.0
            for j, (t2, x2, y2) in enumerate(raw):
                if j == i or j in used or not t2.islower():
                    continue
                d = math.hypot(x2 - x, y2 - y)
                if d < bd:
                    best, bd = j, d
            if best is not None:
                used.add(best)
                out.append((t[:-1] + raw[best][0], x, y))
                continue
        out.append((t, x, y))
    # samme navn flere steder på kartet: behold det første
    seen, uniq = set(), []
    for t, x, y in out:
        k = t.lower()
        if k in seen:
            continue
        seen.add(k); uniq.append((t, x, y))
    return uniq, o


def lookup(name, kommune, zone, cache):
    if name.lower() in cache:
        return cache[name.lower()]
    # API-et overser kommune- og fylkesfiltre, så vi henter mange treff og
    # siler selv på kommunen i svaret.
    url = API + '?' + urllib.parse.urlencode({'sok': name, 'treffPerSide': '50'})
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode('utf-8'))
    except Exception:
        d = {'navn': []}
    hits = []
    for n in d.get('navn', []):
        p = n.get('representasjonspunkt') or {}
        if 'nord' not in p or 'øst' not in p:
            continue
        if kommune and not any(k.get('kommunenavn', '').lower() == kommune.lower()
                               for k in (n.get('kommuner') or [])):
            continue
        hits.append((ll2utm(p['nord'], p['øst'], zone), n.get('skrivemåte'), n.get('navneobjekttype')))
    cache[name.lower()] = hits
    time.sleep(0.2)
    return hits


def fit(places, tol):
    """RANSAC over navnepar. Skalaen er kjent, så avstanden mellom to navn må
    være den samme på kartet og i terrenget."""
    best = None
    for i in range(len(places)):
        for j in range(i + 1, len(places)):
            (n1, x1, y1, h1), (n2, x2, y2, h2) = places[i], places[j]
            dm = math.hypot(x2 - x1, y2 - y1)
            if dm < 500:
                continue
            am = math.atan2(y2 - y1, x2 - x1)
            for p1, _, _ in h1:
                for p2, _, _ in h2:
                    if abs(math.dist(p1, p2) - dm) > tol:
                        continue
                    th = math.atan2(p2[1] - p1[1], p2[0] - p1[0]) - am
                    ca, sa = math.cos(th), math.sin(th)
                    tx = p1[0] - (x1 * ca - y1 * sa)
                    ty = p1[1] - (x1 * sa + y1 * ca)
                    inl = []
                    for n, x, y, hits in places:
                        p = apply(th, tx, ty, (x, y))
                        c = min(hits, key=lambda h: math.dist(h[0], p), default=None)
                        if c and math.dist(c[0], p) <= tol:
                            inl.append(((x, y, 0), (c[0][0], c[0][1], 0, n), math.dist(c[0], p)))
                    sc = (len(inl), -sum(d for _, _, d in inl))
                    if best is None or sc > best[0]:
                        best = (sc, (th, tx, ty), inl)
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ocd')
    ap.add_argument('--kommune', help='avgrens oppslaget, f.eks. Askøy')
    ap.add_argument('--zone', type=int, default=32, help='UTM-sone (32 for Vestlandet)')
    ap.add_argument('--tol', type=float, default=300.0,
                    help='hvor langt navnet kan stå fra punktet det hører til (300 m)')
    ap.add_argument('--fresh', action='store_true', help='ikke bruk mellomlagret oppslag')
    ap.add_argument('--cache', default=os.path.expanduser('~/.cache/aol-stedsnavn.json'))
    args = ap.parse_args()

    names, o = map_names(args.ocd)
    print('%s: 1:%g, %d navn på kartet' % (os.path.basename(args.ocd), o.setup['scale'], len(names)))
    if o.setup['realworld']:
        print('  NB: kartet er allerede georeferert - dette blir en kontroll.')

    cache = {}
    if not args.fresh and os.path.exists(args.cache):
        try: cache = json.load(open(args.cache))
        except Exception: cache = {}
    cache = {k: [((h[0][0], h[0][1]), h[1], h[2]) for h in v] for k, v in cache.items()}

    places = []
    for t, x, y in names:
        hits = lookup(t, args.kommune, args.zone, cache)
        if hits:
            places.append((t, x, y, hits))
    print('%d av dem finnes hos Kartverket%s' % (len(places), ' i ' + args.kommune if args.kommune else ''))
    os.makedirs(os.path.dirname(args.cache), exist_ok=True)
    json.dump({k: [[list(h[0]), h[1], h[2]] for h in v] for k, v in cache.items()}, open(args.cache, 'w'))
    if len(places) < 2:
        sys.exit('For få kjente navn. Prøv uten --kommune, eller georeferer manuelt.')

    best = fit(places, args.tol)
    if not best:
        sys.exit('Fant ingen match mellom navnene på kartet og Kartverkets punkter.')
    th, tx, ty, res, scale = refine([(m, c, d) for m, c, d in best[2]])
    print('\n%d navn stemmer:' % len(best[2]))
    for m, c, d in sorted(best[2], key=lambda p: p[2]):
        print('   %-24s avvik %4.0f m' % (c[3][:24], math.dist(apply(th, tx, ty, m[:2]), c[:2])))
    print('\nAvvik navn-til-punkt: median %.0f m, største %.0f m (navnet står ved siden av det det hører til, '
          'så noen hundre meter er normalt).' % (res[len(res) // 2], res[-1]))
    print('Skalaen i kartet ser %s ut (%.3f).' % ('riktig' if abs(scale - 1) < 0.03 else 'FEIL', scale))
    print('\nTast dette inn i OCAD under Kart > Velg målestokk og referansesystem:')
    print('   Koordinatsystem  UTM %dN (EPSG:%d)' % (args.zone, 32600 + args.zone))
    print('   Øst              %.0f' % tx)
    print('   Nord             %.0f' % ty)
    print('   Vinkel           %.2f°' % math.degrees(th))
    print('\nFinjuster mot flyfoto i OCAD etterpå - navneplassering gir bare grovinnstillingen.')


if __name__ == '__main__':
    main()
