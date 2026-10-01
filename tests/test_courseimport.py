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
from ocad_geo import Georeference                 # noqa: E402


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ocd = fixtures.ocd_map(os.path.join(self.dir, 'testkart.ocd'))
        self.ppen = fixtures.ppen_course(os.path.join(self.dir, 'trening.ppen'))


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
        with open(os.path.join(self.dir, 'livelox-trening.json'), encoding='utf-8') as f:
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

    def test_uten_kart(self):
        r = self.kjor('--no-map')
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.dir, 'livelox-trening.json'), encoding='utf-8') as f:
            self.assertNotIn('maps', json.load(f))

    def test_stopper_uten_georeferering(self):
        with open(self.ocd, 'rb') as f:
            raw = f.read().replace(b'\tr1\t', b'\tr0\t')
        with open(self.ocd, 'wb') as f:
            f.write(raw)
        r = self.kjor()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('ikke georeferert', r.stdout + r.stderr)


class TestOpplasting(Fixtures):
    def setUp(self):
        super().setUp()
        self.url, self.state, self.stop = mock_livelox.start()
        self.addCleanup(self.stop)

    def test_full_import(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, 'livelox_event.py'), self.ppen,
             '--start', '2026-05-12T18:00', '--end', '2026-05-12T21:00',
             '--out', self.dir, '--post'],
            capture_output=True, text=True,
            env=dict(os.environ, LIVELOX_API=self.url, LIVELOX_API_KEY='test'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.state.events), 1)
        eid, ev = next(iter(self.state.events.items()))
        self.assertEqual(ev['name'], 'Testtrening')
        self.assertIn((eid, 'testkart.ocd'), self.state.files)
        self.assertGreater(self.state.files[(eid, 'testkart.ocd')], 0)
        self.assertEqual(self.state.validated, [eid])
        self.assertIn('ImportEvent?importableEventIdentifier=' + eid, r.stdout)

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
