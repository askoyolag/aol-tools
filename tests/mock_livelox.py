"""Minimal etterligning av Livelox' import-API, til bruk i testene.

Lar oss kjøre hele --post-løpet uten klient-id og uten å røre Livelox.
Den tar imot det importerbare arrangementet og filene, og husker dem så
testen kan se hva som faktisk ble sendt.
"""
import http.server, json, threading


class State:
    def __init__(self):
        self.events = {}        # id -> importable event object
        self.files = {}         # (id, filnavn) -> antall bytes
        self.validated = []
        self.imported = set()   # id-er som er fullført i Livelox
        self.reimports = []     # oppdateringer etter fullført import


class Handler(http.server.BaseHTTPRequestHandler):
    state = None

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self):
        return bool(self.headers.get('ApiKey') or self.headers.get('Authorization'))

    def _body(self):
        return self.rfile.read(int(self.headers.get('Content-Length', 0)))

    def do_POST(self):
        if not self._auth_ok():
            return self._send(403, {'error': 'no credentials'})
        body = self._body()
        parts = self.path.strip('/').split('/')
        if parts == ['importableEvents']:
            ev = json.loads(body)
            # Livelox gjenbruker id-en appen oppgir, ellers lager den en ny
            eid = str(ev.get('id') or 'test-' + str(len(self.state.events) + 1))
            self.state.events[eid] = ev
            return self._send(200, {
                'id': eid,
                'liveloxImportEventUrl':
                    'https://www.livelox.com/Admin/Events/ImportEvent?importableEventIdentifier=' + eid})
        if len(parts) == 4 and parts[0] == 'importableEvents' and parts[2] == 'files':
            if parts[1] not in self.state.events:
                return self._send(404, {'error': 'unknown event'})
            from urllib.parse import unquote
            self.state.files[(parts[1], unquote(parts[3]))] = len(body)
            return self._send(201, {})
        self._send(404, {'error': self.path})

    def do_PUT(self):
        if not self._auth_ok():
            return self._send(403, {'error': 'no credentials'})
        body = self._body()
        parts = self.path.strip('/').split('/')
        if len(parts) == 2 and parts[0] == 'importableEvents':
            if parts[1] not in self.state.events:
                return self._send(404, {'error': 'unknown event'})
            self.state.events[parts[1]] = json.loads(body)
            return self._send(200, {'id': parts[1]})
        if len(parts) == 3 and parts[0] == 'importableEvents' and parts[2] == 'import':
            if parts[1] not in self.state.imported:
                return self._send(404, {'error': 'not imported yet'})
            self.state.reimports.append(parts[1])
            return self._send(200, {
                'id': parts[1],
                'liveloxShowEventUrl': 'https://www.livelox.com/Events/Show/4242',
                'liveloxEditEventUrl': 'https://www.livelox.com/Admin/Events/Overview/4242'})
        self._send(404, {'error': self.path})

    def do_GET(self):
        from urllib.parse import urlparse, unquote
        path = urlparse(self.path).path
        parts = path.strip('/').split('/')
        if len(parts) == 2 and parts[0] == 'importableEvents':
            eid = unquote(parts[1])
            if eid not in self.state.events:
                return self._send(404, {'error': 'unknown event'})
            out = dict(self.state.events[eid])
            out['link'] = {'id': eid,
                           'liveloxImportEventUrl':
                               'https://www.livelox.com/Admin/Events/ImportEvent'
                               '?importableEventIdentifier=' + eid}
            if eid in self.state.imported:
                out['importedEvent'] = {'id': 4242, 'name': out.get('name')}
            return self._send(200, out)
        parts = self.path.strip('/').split('/')
        if len(parts) == 3 and parts[2] == 'validationErrors':
            self.state.validated.append(parts[1])
            ev = self.state.events.get(parts[1], {})
            errors = []
            for c in ev.get('courses', []):
                if len(c.get('controls', [])) < 2:
                    errors.append("The course '%s' must have at least two controls." % c.get('name'))
            if not ev.get('maps'):
                errors.append('The event must have a map.')
            return self._send(200, {'errors': errors, 'warnings': []})
        self._send(404, {'error': self.path})

    def log_message(self, *a):
        pass


def start():
    """Starter serveren på en ledig port. Returnerer (url, state, stopp-funksjon)."""
    state = State()
    handler = type('H', (Handler,), {'state': state})
    srv = http.server.HTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def stop():
        srv.shutdown()
        srv.server_close()

    return 'http://127.0.0.1:%d' % srv.server_address[1], state, stop
