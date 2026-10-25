"""Tester for CourseImport: fra .ppen og kartfil til ferdig import i Livelox.

Kjøres med `python3 -m unittest discover tests` fra rota av repoet.
Ingen avhengigheter utover standardbiblioteket, og ingen klubbkart - testfilene
lages av fixtures.py.
"""
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, '..', 'skills', 'livelox-event', 'scripts')
sys.path.insert(0, HERE)
sys.path.insert(0, SCRIPTS)

import fixtures                                   # noqa: E402
import mock_livelox                               # noqa: E402
from ppen import PurplePen                        # noqa: E402
from ocad_geo import Georeference, utm_to_wgs84   # noqa: E402
from ocad import OcadFile                         # noqa: E402
import xml.etree.ElementTree as ET                # noqa: E402


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()               # her havner JSON og XML
        self.area = os.path.join(self.dir, 'Testomrade')   # som en mappe i kartarkivet
        os.makedirs(self.area)
        self.ocd = fixtures.ocd_map(os.path.join(self.area, 'testkart.ocd'),
                                    extent=fixtures.EXTENT)
        self.ppen = fixtures.ppen_course(os.path.join(self.area, 'trening.ppen'))


class TestPurplePen(Fixtures):
    def test_leser_loype(self):
        p = PurplePen(self.ppen)
        self.assertEqual(p.title, 'Testtrening')
        self.assertEqual(p.map_scale, 10000.0)
        c, = p.courses()
        self.assertEqual(c['name'], 'A')
        self.assertEqual([x['kind'] for x in c['controls']],
                         ['start', 'normal', 'normal', 'finish'])
        self.assertEqual(c['length'], fixtures.EXPECTED_LENGTH)


class TestGeoreferering(Fixtures):
    def test_leser_oppsett(self):
        g = Georeference(self.ocd)
        self.assertTrue(g.georeferenced if hasattr(g, 'georeferenced') else g.realworld)
        self.assertEqual(g.epsg, fixtures.EPSG)
        self.assertEqual(tuple(round(v) for v in g.to_projected(0, 0)),
                         tuple(round(v) for v in fixtures.EXPECTED_START))

    def test_millimeter_blir_meter(self):
        g = Georeference(self.ocd)
        x, y = g.to_projected(100, 0)            # 100 mm på 1:10000 = 1000 m
        self.assertAlmostEqual(x - fixtures.X0, 1000.0, places=3)
        self.assertAlmostEqual(y - fixtures.Y0, 0.0, places=3)


class TestRotasjon(unittest.TestCase):
    """Vinkelen i OCAD er positiv med klokka. Feil fortegn ga feil poster i 2026."""

    def kart(self, **kw):
        d = tempfile.mkdtemp()
        return fixtures.ocd_map(os.path.join(d, 'kart.ocd'), **kw)

    def test_herdla_mot_fasit(self):
        g = Georeference(self.kart(**fixtures.HERDLA))
        for kode, ((x, y), (e, n)) in fixtures.HERDLA_POSTER.items():
            pe, pn = g.to_projected(x, y)
            self.assertAlmostEqual(pe, e, delta=0.05, msg='post %s øst' % kode)
            self.assertAlmostEqual(pn, n, delta=0.05, msg='post %s nord' % kode)

    def test_kvart_omdreining(self):
        # Kartnord peker øst for gridnord: høyre på papiret er da sør i terrenget.
        g = Georeference(self.kart(angle=90.0))
        e, n = g.to_projected(100, 0)                    # 100 mm på 1:10000
        self.assertAlmostEqual(e - fixtures.X0, 0.0, places=3)
        self.assertAlmostEqual(n - fixtures.Y0, -1000.0, places=3)

    def test_ocad_files_regner_likt(self):
        path = self.kart(**fixtures.HERDLA)
        (x, y), _ = fixtures.HERDLA_POSTER['38']
        self.assertEqual(OcadFile(path).to_real([(x, y)])[0],
                         Georeference(path).to_projected(x, y))


class TestUtm(unittest.TestCase):
    def test_herdla_start(self):
        _, (e, n) = fixtures.HERDLA_POSTER['S']
        lng, lat = utm_to_wgs84(e, n, 32632)
        self.assertAlmostEqual(lng, fixtures.HERDLA_START_WGS84[0], places=6)
        self.assertAlmostEqual(lat, fixtures.HERDLA_START_WGS84[1], places=6)

    def test_sentralmeridian_og_sorlig_halvkule(self):
        lng, lat = utm_to_wgs84(500000, 6650000, 25832)  # ETRS89 = WGS84 her
        self.assertAlmostEqual(lng, 9.0, places=9)
        self.assertAlmostEqual(lat, 59.9873285392, places=8)
        lng, lat = utm_to_wgs84(400000, 7000000, 32733)
        self.assertAlmostEqual(lng, 13.9910576381, places=8)
        self.assertAlmostEqual(lat, -27.1188458263, places=8)

    def test_ikke_utm(self):
        self.assertIsNone(utm_to_wgs84(100, 100, 3857))


class TestTidssone(unittest.TestCase):
    """Windows-Python har ingen tidssonedatabase uten pakken tzdata."""

    def test_eu_regel_stemmer_med_zoneinfo(self):
        import datetime as dt, livelox_event as le
        try:
            zoneinfo_ok = le.zoneinfo.ZoneInfo('Europe/Oslo')
        except le.zoneinfo.ZoneInfoNotFoundError:
            self.skipTest('ingen tidssonedata å sammenligne med')
        t = dt.datetime(2026, 1, 1)
        while t.year == 2026:                # hver time et helt år, rundt omstillingene
            for tz in ('Europe/Oslo', 'Europe/London', 'Europe/Helsinki'):
                fasit = t.replace(tzinfo=le.zoneinfo.ZoneInfo(tz)).astimezone(dt.timezone.utc)
                self.assertEqual(le._eu_utc(t, tz), fasit.replace(tzinfo=None), (tz, t))
            t += dt.timedelta(hours=7)
        del zoneinfo_ok

    def test_omstilling_2026(self):
        import datetime as dt, livelox_event as le
        self.assertEqual(le._eu_utc(dt.datetime(2026, 10, 22, 18), 'Europe/Oslo'),
                         dt.datetime(2026, 10, 22, 16))       # sommertid
        self.assertEqual(le._eu_utc(dt.datetime(2026, 11, 5, 18), 'Europe/Oslo'),
                         dt.datetime(2026, 11, 5, 17))        # normaltid


class TestBygging(Fixtures):
    def kjor(self, *args, env=None):
        e = dict(os.environ, **(env or {}))
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, 'livelox_event.py'),
                               self.ppen, '--start', '2026-05-12T18:00',
                               '--end', '2026-05-12T21:00', '--out', self.dir, *args],
                              capture_output=True, text=True, env=e)

    def test_bygger_arrangement(self):
        r = self.kjor()
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.dir, 'livelox-testomrade-trening.json'), encoding='utf-8') as f:
            ev = json.load(f)
        self.assertEqual(ev['level'], 'club')            # club = trening i Livelox
        self.assertEqual(ev['country'], 'NOR')
        self.assertEqual(ev['projectionEpsgCode'], fixtures.EPSG)
        self.assertEqual(ev['timeInterval']['start'], '2026-05-12T16:00:00Z')
        self.assertEqual([c['name'] for c in ev['courses']], ['A'])
        self.assertEqual([c['code'] for c in ev['courses'][0]['controls']],
                         ['S', '31', '32', 'F'])
        start, = [c for c in ev['controls'] if c['type'] == 'Start']
        self.assertEqual(round(start['projectedPosition']['x']), round(fixtures.X0))
        self.assertEqual(ev['maps'][0]['fileName'], 'testkart.ocd')
        self.assertNotIn('georeference', ev['maps'][0])   # .ocd bærer den selv

    def test_lager_iof_xml(self):
        r = self.kjor()
        self.assertEqual(r.returncode, 0, r.stderr)
        ns = {'i': 'http://www.orienteering.org/datastandard/3.0'}
        root = ET.parse(os.path.join(self.dir, 'livelox-testomrade-trening.xml')).getroot()
        self.assertEqual(root.get('iofVersion'), '3.0')
        ctrl = {c.find('i:Id', ns).text: c for c in root.iter('{%s}Control' % ns['i'])
                if c.find('i:Id', ns) is not None}
        self.assertEqual(sorted(ctrl), ['31', '32', 'F', 'S'])
        pos = ctrl['S'].find('i:Position', ns)
        lng, lat = utm_to_wgs84(fixtures.X0, fixtures.Y0, fixtures.EPSG)
        self.assertAlmostEqual(float(pos.get('lng')), lng, places=6)
        self.assertAlmostEqual(float(pos.get('lat')), lat, places=6)
        course, = root.iter('{%s}Course' % ns['i'])
        self.assertEqual(course.find('i:Name', ns).text, 'A')
        self.assertEqual([cc.find('i:Control', ns).text for cc in course.findall('i:CourseControl', ns)],
                         ['S', '31', '32', 'F'])
        self.assertEqual([cc.get('type') for cc in course.findall('i:CourseControl', ns)],
                         ['Start', 'Control', 'Control', 'Finish'])

    def test_minner_om_publisering_paa_trening(self):
        r = self.kjor()
        self.assertIn('første start', r.stdout)

    def test_uten_kart(self):
        r = self.kjor('--no-map')
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.dir, 'livelox-testomrade-trening.json'), encoding='utf-8') as f:
            self.assertNotIn('maps', json.load(f))

    def test_stopper_uten_georeferering(self):
        with open(self.ocd, 'rb') as f:
            raw = f.read().replace(b'\tr1\t', b'\tr0\t')
        with open(self.ocd, 'wb') as f:
            f.write(raw)
        r = self.kjor()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('ikke georeferert', r.stdout + r.stderr)


class MedMock(Fixtures):
    """Fixtures pluss en etterligning av Livelox-API-et. Ingen tester her,
    så klassene som arver den ikke kjører hverandres tester om igjen."""
    def setUp(self):
        super().setUp()
        self.url, self.state, self.stop = mock_livelox.start()
        self.addCleanup(self.stop)

    def post(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, 'livelox_event.py'), self.ppen,
             '--start', '2026-05-12T18:00', '--end', '2026-05-12T21:00',
             '--out', self.dir, '--post', *args],
            capture_output=True, text=True,
            env=dict(os.environ, LIVELOX_API=self.url, LIVELOX_API_KEY='test'))


class TestOpplasting(MedMock):

    def test_full_import(self):
        r = self.post()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.state.events), 1)
        eid, ev = next(iter(self.state.events.items()))
        self.assertEqual(ev['name'], 'Testtrening')
        self.assertIn((eid, 'testkart.ocd'), self.state.files)
        self.assertGreater(self.state.files[(eid, 'testkart.ocd')], 0)
        self.assertEqual(self.state.validated, [eid])
        self.assertIn('ImportEvent?importableEventIdentifier=' + eid, r.stdout)

    def test_andre_gang_oppdaterer(self):
        """Samme løypefil to ganger skal ikke lage to arrangementer."""
        self.assertEqual(self.post().returncode, 0)
        eid, = list(self.state.events)
        r = self.post()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.state.events), 1)
        self.assertIn('sender oppdatert versjon', r.stdout)

    def test_oppdatering_etter_import_gaar_uten_nettleser(self):
        self.assertEqual(self.post().returncode, 0)
        eid, = list(self.state.events)
        self.state.imported.add(eid)                 # noen har fullført importen
        r = self.post()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state.external_updates, [eid])
        self.assertIn('Oppdateringen er sendt til Livelox', r.stdout)
        self.assertIn('Events/Show/4242', r.stdout)
        self.assertNotIn('Åpne denne i nettleseren', r.stdout)

    def test_valideringsfeil_stopper(self):
        r = self.post('--no-map')                    # mocken krever kart
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('The event must have a map.', r.stdout)
        self.assertNotIn('Åpne denne i nettleseren', r.stdout)

    def test_utloept_token_fornyes(self):
        """Et utløpt token skal fornyes med refresh-tokenet, uten innlogging."""
        store = os.path.join(self.dir, 'tokens.json')
        with open(store, 'w') as f:
            json.dump({'access_token': 'gammelt', 'refresh_token': 'r1',
                       'expires_in': 86400, 'obtained_at': 0}, f)
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, 'livelox_event.py'), self.ppen,
             '--start', '2026-05-12T18:00', '--end', '2026-05-12T21:00',
             '--out', self.dir, '--post'],
            capture_output=True, text=True,
            env={k: v for k, v in os.environ.items() if k != 'LIVELOX_API_KEY'}
                | {'LIVELOX_API': self.url, 'LIVELOX_TOKEN_FILE': store,
                   'LIVELOX_NO_BROWSER': '1'})
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.state.token_calls, ['refresh_token'])
        with open(store) as f:
            self.assertEqual(json.load(f)['access_token'], 'fornyet-token')
        self.assertEqual(len(self.state.events), 1)

    def test_uten_tilgang(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, 'livelox_event.py'), self.ppen,
             '--start', '2026-05-12T18:00', '--end', '2026-05-12T21:00',
             '--out', self.dir, '--post'],
            capture_output=True, text=True,
            env={k: v for k, v in dict(os.environ, LIVELOX_API=self.url).items()
                 if k not in ('LIVELOX_API_KEY',)} | {'LIVELOX_TOKEN_FILE': os.path.join(self.dir, 'ingen.json'),
                                                      'LIVELOX_NO_BROWSER': '1'})
        self.assertNotEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()


# ---------------------------------------------------------------- id og status
import state                                       # noqa: E402


class TestId(unittest.TestCase):
    def test_samme_filnavn_i_ulike_mapper_gir_ulike_id(self):
        a = state.new_id('/arkiv/Herdla/Trening sept 2026.ppen')
        b = state.new_id('/arkiv/Flagget/Trening sept 2026.ppen')
        self.assertEqual(a, 'herdla-trening-sept-2026')
        self.assertNotEqual(a, b)

    def test_gammel_id_er_bare_filnavnet(self):
        # Må være byte for byte lik ordningen før 25.10, ellers finner
        # oppryddingen ikke utkastene som ble sendt med den.
        self.assertEqual(state.old_id('/arkiv/Herdla/Trening sept 2026.ppen'), 'trening-sept-2026')

    def test_lange_navn_kortes_med_hash(self):
        i = state.new_id('/a/Friluften-Hanøy-Ramsøy/' + 'Veldig langt navn ' * 6 + '.ppen')
        self.assertLessEqual(len(i), 64)
        self.assertRegex(i, r'-[0-9a-f]{7}$')

    def test_samme_id_paa_windows_og_linux(self):
        self.assertEqual(state.new_id('C:/Users/x/OneDrive/AOL-Kart/Herdla/Trening sept 2026.ppen'),
                         state.new_id('/sessions/y/mnt/AOL-Kart/Herdla/Trening sept 2026.ppen'))


class TestKontroller(Fixtures):
    def kjor(self, *args):
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, 'livelox_event.py'), self.ppen,
                               '--start', '2026-05-12T18:00', '--end', '2026-05-12T21:00',
                               '--out', self.dir, *args], capture_output=True, text=True)

    def test_tom_loypefil_stopper(self):
        fixtures.ppen_course(self.ppen, ppen=fixtures.PPEN_TOM)
        r = self.kjor()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('ingen løyper', r.stdout + r.stderr)

    def test_post_utenfor_kartet_stopper(self):
        fixtures.ppen_course(self.ppen, ppen=fixtures.PPEN_UTENFOR)
        r = self.kjor()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('utenfor kartet', r.stdout + r.stderr)
        self.assertIn('32', r.stdout + r.stderr)

    def test_utenfor_kan_overstyres(self):
        fixtures.ppen_course(self.ppen, ppen=fixtures.PPEN_UTENFOR)
        self.assertEqual(self.kjor('--allow-outside').returncode, 0)


class TestStatusOgKontroll(MedMock):
    def test_statusfil_skrives(self):
        self.assertEqual(self.post().returncode, 0)
        rec = state.load(self.ppen)
        self.assertEqual(rec['id'], 'testomrade-trening')
        self.assertFalse(rec['imported'])
        self.assertIn('ImportEvent', rec['import_url'])
        self.assertEqual(rec['map_file'], 'testkart.ocd')
        self.assertEqual(len(rec['map_sha256']), 64)

    def test_id_fra_statusfila_vinner(self):
        """Slik beholder et importert arrangement id-en fra før ordningen ble endret."""
        state.save(self.ppen, {'id': 'trening'})
        self.assertEqual(self.post().returncode, 0)
        self.assertEqual(list(self.state.events), ['trening'])

    def test_statusfila_faar_vite_om_importen(self):
        self.post()
        eid, = list(self.state.events)
        self.state.imported.add(eid)
        self.post()
        rec = state.load(self.ppen)
        self.assertTrue(rec['imported'])
        self.assertEqual(rec['livelox_event_id'], 4242)

    def test_kontroll_stemmer(self):
        self.post()
        self.state.imported.add(next(iter(self.state.events)))
        self.state.courses_read = True
        r = self.post('--verify')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('alt stemmer', r.stdout)

    def test_kontroll_finner_avvik(self):
        self.post()
        self.state.imported.add(next(iter(self.state.events)))
        self.state.courses_read = True
        ev = json.load(open(os.path.join(self.dir, 'livelox-testomrade-trening.json'), encoding='utf-8'))
        ev['courses'][0]['controls'] = [{'code': c} for c in ('S', '32', '31', 'F')]
        lonlat = {c['code']: utm_to_wgs84(c['projectedPosition']['x'], c['projectedPosition']['y'],
                                          ev['projectionEpsgCode']) for c in ev['controls']}
        import iof_xml
        self.state.iof_override = iof_xml.course_data(ev, lonlat)
        r = self.post('--verify')
        self.assertIn('1 avvik', r.stdout)
        self.assertIn('S-32-31-F', r.stdout)

    def test_kontroll_uten_scope(self):
        self.post()
        self.state.imported.add(next(iter(self.state.events)))
        r = self.post('--verify')
        self.assertEqual(r.returncode, 0)
        self.assertIn('courses.read', r.stdout)


# ---------------------------------------------------------------- batch
class TestBatch(MedMock):
    def batch(self, *args):
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, 'livelox_batch.py'), *args],
                              capture_output=True, text=True,
                              env=dict(os.environ, LIVELOX_API=self.url, LIVELOX_API_KEY='test'))

    def plan(self, **item):
        p = os.path.join(self.dir, 'plan.json')
        entry = dict(ppen='Testomrade/trening.ppen', start='2026-09-10T18:00',
                     end='2026-09-10T20:00', name='Trening 10.09.2026')
        entry.update(item)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump([entry], f)
        return p

    def test_plan_sendes_og_uendret_hoppes_over(self):
        p = self.plan()
        r = self.batch('run', p, '--yes')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('opprettes', r.stdout)
        self.assertEqual(self.state.events['testomrade-trening']['name'], 'Trening 10.09.2026')
        self.state.imported.add('testomrade-trening')
        self.batch('run', p, '--yes')                  # første etter import: lagrer fingeravtrykket
        r = self.batch('run', p, '--yes')
        self.assertIn('uendret, hoppes over', r.stdout)
        self.assertIn('Ingenting å sende', r.stdout)

    def test_plan_uten_dato_avvises(self):
        r = self.batch('run', self.plan(start=None), '--yes')
        self.assertIn('mangler start', r.stdout)
        self.assertEqual(self.state.events, {})

    def test_plan_krever_bekreftelse(self):
        r = self.batch('run', self.plan())             # ingen terminal, ingen --yes
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('--yes', r.stdout + r.stderr)
        self.assertEqual(self.state.events, {})

    def test_cleanup_sletter_bare_uimporterte_utkast(self):
        fixtures.ppen_course(os.path.join(self.area, 'sept.ppen'))
        self.state.events['trening'] = {'name': 'gammelt utkast'}     # gammel id, ikke importert
        self.state.events['sept'] = {'name': 'importert'}             # gammel id, importert
        self.state.imported.add('sept')
        r = self.batch('cleanup', self.dir, '--yes')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state.deleted, ['trening'])
        self.assertIn('importert, ikke rørt', r.stdout)

    def test_adopt_knytter_fil_til_importert_id(self):
        self.state.events['trening-sept-2026'] = {'name': 'Trening 10.09.2026'}
        self.state.imported.add('trening-sept-2026')
        r = self.batch('adopt', self.ppen, '--id', 'trening-sept-2026')
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = state.load(self.ppen)
        self.assertEqual(rec['id'], 'trening-sept-2026')
        self.assertTrue(rec['imported'])
