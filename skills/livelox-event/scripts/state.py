"""Id-er og statusfil for løypefiler som sendes til Livelox.

Livelox gjenbruker id-en vi oppgir for et importerbart arrangement. Den må
derfor være stabil over tid og unik i hele kartarkivet. Den første ordningen
brukte bare filnavnet, og da ville tolv filer fra 2026 med samme navn i hver
sin mappe overskrevet hverandre. Nå bygges id-en av mappe og filnavn.

Ved siden av hver løypefil ligger en liten statusfil, `<løypefil>.livelox.json`,
som husker id, når og hva som ble sendt, og om arrangementet er importert.
Finnes den, er id-en i den gjeldende - slik beholder et arrangement som alt
er importert id-en sin selv om ordningen for nye id-er endres.
"""
import datetime as dt, hashlib, json, os, re

SUFFIX = '.livelox.json'
MAX_ID = 64


def slug(text):
    s = text.lower().replace('æ', 'ae').replace('ø', 'o').replace('å', 'a')
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', s)).strip('-')


def _stem(ppen):
    return os.path.splitext(os.path.basename(ppen))[0]


def _folder(ppen):
    return os.path.basename(os.path.dirname(os.path.abspath(ppen)))


def new_id(ppen):
    """Mappe + filnavn. Bare navnene brukes, ikke hele stien, så id-en blir lik
    på Windows, i Linux-VM-en og i skyen."""
    key = '%s/%s' % (_folder(ppen), _stem(ppen))
    s = slug(key.replace('/', '-'))
    if len(s) <= MAX_ID:
        return s
    tail = hashlib.sha1(key.encode('utf-8')).hexdigest()[:7]
    return s[:MAX_ID - 8].rstrip('-') + '-' + tail


def old_id(ppen):
    """Ordningen før 25.10.2026: bare filnavnet. Brukes til opprydding."""
    return slug(_stem(ppen))[:MAX_ID]


def path(ppen):
    return ppen + SUFFIX


def load(ppen):
    try:
        with open(path(ppen), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(ppen, data):
    data = dict(data, updated=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat())
    with open(path(ppen), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def event_id(ppen, explicit=None):
    """--id vinner, deretter statusfila, og til slutt den nye ordningen."""
    return explicit or load(ppen).get('id') or new_id(ppen)


def file_sha256(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(chunk), b''):
            h.update(b)
    return h.hexdigest()


def event_sha256(ev):
    """Fingeravtrykk av det som faktisk sendes, så status kan si om
    løypefila er endret siden sist."""
    return hashlib.sha256(json.dumps(ev, sort_keys=True, ensure_ascii=False)
                          .encode('utf-8')).hexdigest()
