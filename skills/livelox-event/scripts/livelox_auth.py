"""OAuth2 (Authorization Code + PKCE) mot Livelox.

Livelox gir ikke klubber API-nøkkel; verktøy som dette autoriseres av brukeren
selv, slik OCAD gjør det. Første gang åpnes nettleseren der løypeleggeren
logger inn og godkjenner. Tokenet lagres lokalt og fornyes automatisk –
refresh-token utløper ikke, så dette skjer én gang per maskin.

Klient-id og redirect-URI avtales med info@livelox.com.
"""
import base64, hashlib, http.server, json, os, secrets, sys, time
import threading, urllib.error, urllib.parse, urllib.request, webbrowser

AUTHORIZE = 'https://api.livelox.com/oauth2/authorize'
TOKEN = 'https://api.livelox.com/oauth2/token'
CLIENT_ID = os.environ.get('LIVELOX_CLIENT_ID', 'CourseImport')
REDIRECT = os.environ.get('LIVELOX_REDIRECT_URI', 'http://localhost:8731/livelox/callback')
SCOPE = 'events.import'
STORE = os.path.expanduser(os.environ.get('LIVELOX_TOKEN_FILE', '~/.config/livelox/tokens.json'))


def _save(tok):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, 'w') as f:
        json.dump(tok, f)
    os.chmod(STORE, 0o600)


def _load():
    try:
        with open(STORE) as f:
            return json.load(f)
    except Exception:
        return None


def _post(body):
    data = urllib.parse.urlencode(body).encode()
    req = urllib.request.Request(TOKEN, data=data, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


class _Catch(http.server.BaseHTTPRequestHandler):
    code = None

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Catch.code = (q.get('code', [None])[0], q.get('state', [None])[0])
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write('<h2>Takk – Livelox er koblet til.</h2>'
                         '<p>Du kan lukke dette vinduet.</p>'.encode('utf-8'))

    def log_message(self, *a):
        pass


def authorize(client_id=CLIENT_ID, redirect_uri=REDIRECT, scope=SCOPE):
    """Kjører innloggingen og returnerer et ferskt token-sett."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip('=')
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode('ascii')).digest()).decode().rstrip('=')
    state = secrets.token_urlsafe(16)
    url = AUTHORIZE + '?' + urllib.parse.urlencode({
        'response_type': 'code', 'scope': scope, 'redirect_uri': redirect_uri,
        'client_id': client_id, 'state': state,
        'code_challenge': challenge, 'code_challenge_method': 'S256'})

    parts = urllib.parse.urlparse(redirect_uri)
    srv = http.server.HTTPServer((parts.hostname or 'localhost', parts.port or 80), _Catch)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    print('Åpner nettleseren for innlogging i Livelox...')
    if not webbrowser.open(url):
        print('Åpne denne adressen selv:\n  %s' % url)
    for _ in range(600):                      # inntil fem minutter
        if _Catch.code:
            break
        time.sleep(0.5)
    code, got_state = _Catch.code or (None, None)
    if not code:
        sys.exit('Fikk ingen autorisasjonskode fra Livelox.')
    if got_state != state:
        sys.exit('State stemmer ikke – avbryter.')
    tok = _post({'grant_type': 'authorization_code', 'code': code,
                 'client_id': client_id, 'code_verifier': verifier, 'scope': scope})
    _save(tok)
    return tok


def access_token(client_id=CLIENT_ID, interactive=True):
    """Gyldig access token, med fornyelse og innlogging ved behov."""
    tok = _load()
    if not tok:
        if not interactive:
            return None
        tok = authorize(client_id=client_id)
    return tok.get('access_token')


def refresh(client_id=CLIENT_ID):
    tok = _load()
    if not tok or not tok.get('refresh_token'):
        return None
    try:
        new = _post({'grant_type': 'refresh_token', 'client_id': client_id,
                     'refresh_token': tok['refresh_token']})
    except urllib.error.HTTPError:
        return None
    new.setdefault('refresh_token', tok['refresh_token'])
    _save(new)
    return new.get('access_token')


if __name__ == '__main__':
    t = authorize()
    print('Innlogget. Token lagret i %s (utløper om %s sekunder).'
          % (STORE, t.get('expires_in')))
