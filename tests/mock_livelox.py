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

    def do_POST(self):
        if not self._auth_ok():
            return self._send(403, {'error': 'no credentials'})
        n = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(n)
        parts = self.path.strip('/').split('/')
        if parts == ['importableEvents']:
            ev = json.loads(body)
            eid = 'test-' + str(len(self.state.events) + 1)
            self.state.events[eid] = ev
            return self._send(200, {
                'id': eid,
                'liveloxImportEventUrl':
                    'https://www.livelox.com/Admin/Events/ImportEvent?importableEventIdentifier=' + eid})
        if len(parts) == 4 and parts[0] == 'importableEvents' and parts[2] == 'files':
            from urllib.parse import unquote
            self.state.files[(parts[1], unquote(parts[3]))] = len(body)
            return self._send(201, {})
        self._send(404, {'error': self.path})

    def do_GET(self):
        parts = self.path.strip('/').split('/')
        if len(parts) == 3 and parts[2] == 'validationErrors':
            self.state.validated.append(parts[1])
            ev = self.state.events.get(parts[1], {})
            errors = []
            for c in ev.get('courses', []):
                if len(c.get('controls', [])) < 2:
                    errors.append("The course '%s' must have at least two controls." % c.get('name'))
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
