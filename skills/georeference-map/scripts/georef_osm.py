#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Finn georefereringen til et ugeoreferert OCAD-kart ved å matche vannflater
mot OpenStreetMap.

Orienteringskart tegnes ofte uten referansesystem. Innsjøer og tjern er
distinkte, stabile og finnes både i kartet og i OSM (i Norge i stor grad
importert fra N50), så de kan brukes til å regne ut rotasjonen og origo som
OCAD trenger. Skriptet skriver ingenting i kartfila – det gir deg tallene du
taster inn under `Kart > Velg målestokk og referansesystem`.

  python3 georef_osm.py kart.ocd --place "Fauskanger, Askøy"
  python3 georef_osm.py kart.ocd --bbox 60.47,4.95,60.56,5.12

Metoden er kartverk-uavhengig: enhver kilde med vannflater i kjente koordinater
kan brukes i stedet for OSM (Kartverkets N50, mapant.no, kommunale data).
"""
import argparse, json, math, os, re, sys, time, urllib.parse, urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', '..', 'ocad-files', 'scripts'))
from ocad import OcadFile                     # noqa: E402
from ocad_print import symbol_table           # noqa: E402

UA = 'aol-tools georef (https://github.com/askoy-ol)'
OVERPASS = ['https://overpass-api.de/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter']
WATER_RE = re.compile(r'\b(sjö|innsjø|vatn|vann|tjern|tjørn|göl|lake|water|dam|damm)\w*', re.I)
WATER_SYMS = range(301000, 307000)      # ISOM: 301-306 er vann, 307+ er myr


# ---------------------------------------------------------------- geometri
def utm_zone(lat, lon):
    """UTM-sone med unntakene: Norge bruker sone 32 helt vest til 3°E, og
    Svalbard har sine egne utvidede soner."""
    z = int(math.floor((lon+180)/6))+1
    if 56 <= lat < 64 and 3 <= lon < 12:
        return 32
    if 72 <= lat < 84 and 0 <= lon < 42:
        return {0: 31, 9: 33, 21: 35, 33: 37}[max(k for k in (0, 9, 21, 33) if lon >= k)]
    return z


def ll2utm(lat, lon, zone):
    a, f, k0 = 6378137.0, 1/298.257223563, 0.9996
    e2 = f*(2-f); ep2 = e2/(1-e2)
    lat, lon = math.radians(lat), math.radians(lon)
    lon0 = math.radians((zone-1)*6-180+3)
    N = a/math.sqrt(1-e2*math.sin(lat)**2); T = math.tan(lat)**2
    C = ep2*math.cos(lat)**2; A = math.cos(lat)*(lon-lon0)
    M = a*((1-e2/4-3*e2**2/64-5*e2**3/256)*lat-(3*e2/8+3*e2**2/32+45*e2**3/1024)*math.sin(2*lat)
           + (15*e2**2/256+45*e2**3/1024)*math.sin(4*lat)-(35*e2**3/3072)*math.sin(6*lat))
    E = k0*N*(A+(1-T+C)*A**3/6+(5-18*T+T**2+72*C-58*ep2)*A**5/120)+500000.0
    Nn = k0*(M+N*math.tan(lat)*(A**2/2+(5-T+9*C+4*C**2)*A**4/24
             + (61-58*T+T**2+600*C-330*ep2)*A**6/720))
    return E, Nn


def area_centroid(pts):
    if len(pts) < 3:
        return 0.0, None
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]+pts[:1]):
        cr = x1*y2-x2*y1; a += cr; cx += (x1+x2)*cr; cy += (y1+y2)*cr
    if abs(a) < 1e-9:
        return 0.0, None
    return abs(a)/2.0, (cx/(3*a), cy/(3*a))


def apply(th, tx, ty, p):
    ca, sa = math.cos(th), math.sin(th)
    return (p[0]*ca-p[1]*sa+tx, p[0]*sa+p[1]*ca+ty)


# ---------------------------------------------------------------- kilder
def water_symbols(o):
    """Symbolnumre for vannflater.

    ISOM legger vann på 301-306 og myr på 307 og oppover, så nummeret avgjør.
    Beskrivelsen brukes bare til å ta med symboler utenfor serien - og den må
    sjekkes mot ordgrenser: "Vegetasjon" inneholder "sjo".
    """
    table = symbol_table(o)
    found = {s for s, d in table.items() if d['otp'] == 3 and s in WATER_SYMS}
    found |= {s for s, d in table.items()
              if d['otp'] == 3 and d['desc'] and WATER_RE.match(d['desc'].strip())}
    return found or {301000, 302000}


def map_water(path, min_area, max_area):
    """Vannflater i kartets lokale meter. Bare ytre ring – resten er holmer."""
    o = OcadFile(path)
    syms = water_symbols(o)
    f = (o.setup['scale'] or 10000.0)/1000.0
    out = []
    for ob in o.objects():
        if ob['sym'] not in syms or ob['otp'] != 3 or not ob['rings']:
            continue
        pts = [(x*f, y*f) for x, y in ob['rings'][0]]
        ar, c = area_centroid(pts)
        if c and min_area <= ar <= max_area:
            out.append((c[0], c[1], ar))
    out.sort(key=lambda t: -t[2])
    return out, o, syms


def fetch(url, data=None, tries=2):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            if i == tries-1:
                raise
            time.sleep(3 + 5*i)


def geocode(place):
    url = 'https://nominatim.openstreetmap.org/search?format=json&limit=1&q=' \
          + urllib.parse.quote(place)
    res = fetch(url)
    if not res:
        sys.exit('Fant ikke stedet "%s". Bruk --bbox i stedet.' % place)
    bb = [float(v) for v in res[0]['boundingbox']]      # sør, nord, vest, øst
    pad = 0.03
    return (bb[0]-pad, bb[2]-pad, bb[1]+pad, bb[3]+pad), res[0]['display_name']


def osm_water(bbox, zone, min_area, cache):
    if cache and os.path.exists(cache):
        data = json.load(open(cache))
    else:
        q = ('[out:json][timeout:120];way["natural"="water"](%f,%f,%f,%f);out geom;' % bbox)
        last = None
        for url in OVERPASS:
            try:
                data = fetch(url, data=('data='+urllib.parse.quote(q)).encode()); last = None; break
            except Exception as e:
                last = e
        if last:
            sys.exit('Overpass svarte ikke: %s' % last)
        if cache:
            json.dump(data, open(cache, 'w'))
    out = []
    for e in data['elements']:
        g = e.get('geometry')
        if not g:
            continue
        ar, c = area_centroid([ll2utm(p['lat'], p['lon'], zone) for p in g])
        if c and ar >= min_area:
            out.append((c[0], c[1], ar, (e.get('tags') or {}).get('name')))
    out.sort(key=lambda t: -t[2])
    return out


# ---------------------------------------------------------------- matching
def match(M, O, dist_tol=40.0, ratio=2.5, inlier_tol=60.0, n_map=25, n_osm=400, min_sep=300.0):
    """Finner rotasjon+forflytning ved å prøve par av vann mot par av vann.

    Skalaen er kjent (kartets målestokk), så avstanden mellom to vann må være
    den samme i kart og terreng – det siler bort nesten alle falske par.
    """
    M, O = M[:n_map], O[:n_osm]
    best = None
    for i in range(len(M)):
        for j in range(i+1, len(M)):
            dm = math.dist(M[i][:2], M[j][:2])
            if dm < min_sep:
                continue
            am = math.atan2(M[j][1]-M[i][1], M[j][0]-M[i][0])
            for k in range(len(O)):
                if not 1/ratio <= O[k][2]/M[i][2] <= ratio:
                    continue
                for l in range(len(O)):
                    if l == k or not 1/ratio <= O[l][2]/M[j][2] <= ratio:
                        continue
                    if abs(math.dist(O[k][:2], O[l][:2])-dm) > dist_tol:
                        continue
                    th = math.atan2(O[l][1]-O[k][1], O[l][0]-O[k][0])-am
                    ca, sa = math.cos(th), math.sin(th)
                    tx = O[k][0]-(M[i][0]*ca-M[i][1]*sa)
                    ty = O[k][1]-(M[i][0]*sa+M[i][1]*ca)
                    inl = pair_up(M, O, th, tx, ty, inlier_tol, ratio)
                    sc = (len(inl), -sum(d for _, _, d in inl))
                    if best is None or sc > best[0]:
                        best = (sc, (th, tx, ty), inl)
    return best


def pair_up(M, O, th, tx, ty, tol, ratio):
    cand = []
    for m in M:
        p = apply(th, tx, ty, m[:2])
        c = min(O, key=lambda o: math.dist(o[:2], p))
        d = math.dist(c[:2], p)
        if d <= tol and 1/ratio <= c[2]/m[2] <= ratio:
            cand.append((d, m, c))
    out, used = [], set()                       # ett kartvann per osm-vann
    for d, m, c in sorted(cand):
        key = (round(c[0], 1), round(c[1], 1))
        if key in used:
            continue
        used.add(key); out.append((m, c, d))
    return out


def refine(pairs):
    n = len(pairs)
    mx = sum(m[0] for m, _, _ in pairs)/n; my = sum(m[1] for m, _, _ in pairs)/n
    ox = sum(c[0] for _, c, _ in pairs)/n; oy = sum(c[1] for _, c, _ in pairs)/n
    num = sum((m[0]-mx)*(c[1]-oy)-(m[1]-my)*(c[0]-ox) for m, c, _ in pairs)
    den = sum((m[0]-mx)*(c[0]-ox)+(m[1]-my)*(c[1]-oy) for m, c, _ in pairs)
    var = sum((m[0]-mx)**2+(m[1]-my)**2 for m, _, _ in pairs) or 1.0
    th = math.atan2(num, den); ca, sa = math.cos(th), math.sin(th)
    tx = ox-(mx*ca-my*sa); ty = oy-(mx*sa+my*ca)
    res = sorted(math.dist(apply(th, tx, ty, m[:2]), c[:2]) for m, c, _ in pairs)
    return th, tx, ty, res, math.hypot(num, den)/var


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ocd')
    ap.add_argument('--place', help='stedsnavn kartet dekker, f.eks. "Fauskanger, Askøy"')
    ap.add_argument('--bbox', help='sør,vest,nord,øst i grader')
    ap.add_argument('--zone', type=int, help='UTM-sone (standard: utledet av lengdegraden)')
    ap.add_argument('--min-area', type=float, default=3000.0, help='minste vannflate i m² (3000)')
    ap.add_argument('--max-area', type=float, default=400000.0, help='største vannflate i m² – holder sjøen utenfor')
    ap.add_argument('--tol', type=float, default=60.0, help='hvor nær to vann må ligge for å regnes som samme (60 m)')
    ap.add_argument('--cache', help='mellomlagre OSM-svaret i denne fila')
    args = ap.parse_args()

    if args.bbox:
        bbox = tuple(float(v) for v in args.bbox.split(',')); where = 'oppgitt område'
    elif args.place:
        bbox, where = geocode(args.place)
    else:
        sys.exit('Oppgi --place eller --bbox så vi vet hvor i verden kartet ligger.')
    zone = args.zone or utm_zone((bbox[0]+bbox[2])/2, (bbox[1]+bbox[3])/2)
    epsg = 32600+zone

    M, o, syms = map_water(args.ocd, args.min_area, args.max_area)
    print('%s: 1:%g, %d vannflater (symbol %s)'
          % (os.path.basename(args.ocd), o.setup['scale'], len(M),
             ', '.join(str(s//1000) for s in sorted(syms))))
    if o.setup['realworld']:
        print('  NB: kartet er allerede georeferert – dette blir en kontroll.')
    O = osm_water(bbox, zone, args.min_area, args.cache)
    print('%s: %d vannflater fra OSM, UTM-sone %d (EPSG:%d)' % (where[:60], len(O), zone, epsg))
    if len(M) < 2 or len(O) < 2:
        sys.exit('For få vannflater til å matche. Prøv lavere --min-area eller et større område.')

    best = match(M, O, inlier_tol=args.tol)
    if not best:
        sys.exit('Fant ingen match. Sjekk at området stemmer, eller senk --min-area.')
    th, tx, ty, res, scale = refine(best[2])

    print('\n%d vann matchet:' % len(best[2]))
    for m, c, _ in sorted(best[2], key=lambda p: -p[0][2]):
        print('   %-22s kart %7.0f m²  osm %7.0f m²  avvik %4.0f m'
              % ((c[3] or 'uten navn')[:22], m[2], c[2],
                 math.dist(apply(th, tx, ty, m[:2]), c[:2])))
    print('\nAvvik: median %.0f m, største %.0f m. Skalaen i kartet ser %s ut (%.3f).'
          % (res[len(res)//2], res[-1],
             'riktig' if abs(scale-1) < 0.02 else 'FEIL', scale))
    print('\nTast dette inn i OCAD under Kart > Velg målestokk og referansesystem:')
    print('   Koordinatsystem  UTM %dN (EPSG:%d)' % (zone, epsg))
    print('   Øst              %.1f' % tx)
    print('   Nord             %.1f' % ty)
    print('   Vinkel           %.3f°' % math.degrees(th))
    print('\nKontroller alltid resultatet mot flyfoto før kartet brukes.')


if __name__ == '__main__':
    main()
