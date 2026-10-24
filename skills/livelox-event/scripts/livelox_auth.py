#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""OAuth2 (Authorization Code + PKCE) mot Livelox.

Livelox gir ikke klubber API-nøkkel; verktøy som dette autoriseres av brukeren
selv, slik OCAD gjør det. Første gang åpnes nettleseren der løypeleggeren
logger inn og godkjenner. Tokenet lagres lokalt og fornyes automatisk –
refresh-token utløper ikke, så dette skjer én gang per maskin.

Klient-id-en `CourseImport` er registrert hos Livelox og brukes av alle
klubber; redirect-URI-en er ikke forhåndsregistrert, så vi velger en ledig
port ved kjøring (RFC 8252) i stedet for å låse en som kan være i bruk.

  python3 livelox_auth.py              # logg inn
  python3 livelox_auth.py --status     # hvem er innlogget
  python3 livelox_auth.py --logout     # glem tokenet
"""
import argparse, base64, hashlib, http.server, json, os, secrets, sys
import threading, time, urllib.error, urllib.parse, urllib.request, webbrowser

API_BASE = os.environ.get('LIVELOX_API', 'https://api.livelox.com')
AUTHORIZE = API_BASE + '/oauth2/authorize'
TOKEN = API_BASE + '/oauth2/token'
CLIENT_ID = os.environ.get('LIVELOX_CLIENT_ID', 'CourseImport')
SCOPE = 'events.import'
CALLBACK_PATH = '/livelox/callback'
STORE = os.path.expanduser(os.environ.get('LIVELOX_TOKEN_FILE', '~/.config/livelox/tokens.json'))


# ---------------------------------------------------------------- lagring
def _save(tok):
    tok = dict(tok, obtained_at=time.time())
    os.makedirs(os.path.dirname(STORE) or '.', exist_ok=True)
    with open(STORE, 'w') as f:
        json.dump(tok, f)
    try:
        os.chmod(STORE, 0o600)
    except OSError:
        pass                                   # Windows bryr seg ikke
    return tok


def _load():
    try:
        with open(STORE) as f:
            return json.load(f)
    except Exception:
        return None


def _expired(tok, margin=300):
    """Sant når tokenet er utløpt, eller så nær at et kall kan rekke å feile."""
    try:
        return tok['obtained_at'] + float(tok.get('expires_in', 0)) - margin < time.time()
    except (KeyError, TypeError, ValueError):
        return True                            # ukjent alder: fornye er tryggest


def _post(body):
    data = urllib.parse.urlencode(body).encode()
    req = urllib.request.Request(TOKEN, data=data, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


# ---------------------------------------------------------------- innlogging
class _Catch(http.server.BaseHTTPRequestHandler):
    got = None

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Catch.got = (q.get('code', [None])[0], q.get('state', [None])[0],
                      q.get('error', [None])[0])
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write('<h2>Takk – Livelox er koblet til.</h2>'
                         '<p>Du kan lukke dette vinduet.</p>'.encode('utf-8'))

    def log_message(self, *a):
        pass


def authorize(client_id=CLIENT_ID, redirect_uri=None, scope=SCOPE, timeout=300):
    """Kjører innloggingen og returnerer et ferskt token-sett.

    Uten oppgitt redirect-URI bindes en ledig port, og adressen bygges av
    porten vi faktisk fikk. Livelox godtar enhver loopback-adresse så lenge
    noe lytter der.
    """
    redirect_uri = redirect_uri or os.environ.get('LIVELOX_REDIRECT_URI')
    port, path = 0, CALLBACK_PATH
    if redirect_uri:
        u = urllib.parse.urlparse(redirect_uri)
        port, path = u.port or 80, u.path or '/'
    try:
        srv = http.server.HTTPServer(('127.0.0.1', port), _Catch)
    except OSError as e:
        sys.exit('Fikk ikke åpnet port %s for innloggingen: %s' % (port or 'automatisk', e))
    port = srv.server_address[1]
    if not redirect_uri:
        redirect_uri = 'http://localhost:%d%s' % (port, path)

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip('=')
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode('ascii')).digest()).decode().rstrip('=')
    state = secrets.token_urlsafe(16)
    url = AUTHORIZE + '?' + urllib.parse.urlencode({
        'response_type': 'code', 'scope': scope, 'redirect_uri': redirect_uri,
        'client_id': client_id, 'state': state,
        'code_challenge': challenge, 'code_challenge_method': 'S256'})

    _Catch.got = None
    threading.Thread(target=srv.handle_request, daemon=True).start()
    print('Logg inn i Livelox i nettleseren som åpner seg.')
    if os.environ.get('LIVELOX_NO_BROWSER') or not webbrowser.open(url):
        print('Åpne denne adressen selv:\n  %s' % url)
    deadline = time.time() + timeout
    while _Catch.got is None and time.time() < deadline:
        time.sleep(0.25)
    srv.server_close()

    if _Catch.got is None:
        sys.exit('Ingen svar fra Livelox innen %d sekunder.' % timeout)
    code, got_state, error = _Catch.got
    if error:
        sys.exit('Livelox avviste forespørselen: %s' % error)
    if got_state != state:
        sys.exit('State stemmer ikke – avbryter innloggingen.')
    if not code:
        sys.exit('Fikk ingen autorisasjonskode fra Livelox.')
    return _save(_post({'grant_type': 'authorization_code', 'code': code,
                        'client_id': client_id, 'code_verifier': verifier,
                        'scope': scope, 'redirect_uri': redirect_uri}))


def refresh(client_id=CLIENT_ID):
    tok = _load()
    if not tok or not tok.get('refresh_token'):
        return None
    try:
        new = _post({'grant_type': 'refresh_token', 'client_id': client_id,
                     'refresh_token': tok['refresh_token']})
    except (urllib.error.HTTPError, urllib.error.URLError):
        return None
    new.setdefault('refresh_token', tok['refresh_token'])
    return _save(new).get('access_token')


def access_token(client_id=CLIENT_ID, interactive=True):
    """Gyldig access token, med fornyelse og innlogging ved behov."""
    tok = _load()
    if tok and not _expired(tok):
        return tok.get('access_token')
    if tok:
        fresh = refresh(client_id)
        if fresh:
            return fresh
    if not interactive:
        return None
    return authorize(client_id=client_id).get('access_token')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--status', action='store_true', help='vis om maskinen er innlogget')
    ap.add_argument('--logout', action='store_true', help='slett det lagrede tokenet')
    args = ap.parse_args()

    if args.logout:
        if os.path.exists(STORE):
            os.remove(STORE)
            print('Tokenet er slettet (%s).' % STORE)
        else:
            print('Ingen token lagret.')
        return
    if args.status:
        tok = _load()
        if not tok:
            print('Ikke innlogget. Kjør dette skriptet uten argumenter.')
            return
        rest = tok.get('obtained_at', 0) + float(tok.get('expires_in', 0)) - time.time()
        print('Innlogget som klient %s.' % CLIENT_ID)
        print('Access token %s (%s).' % ('utløpt' if rest <= 0 else 'gyldig',
                                         'fornyes ved behov' if tok.get('refresh_token')
                                         else 'uten refresh-token'))
        print('Lagret i %s' % STORE)
        return

    tok = authorize()
    print('Innlogget. Tokenet er lagret i %s og varer i %s sekunder.'
          % (STORE, tok.get('expires_in')))


if __name__ == '__main__':
    main()
