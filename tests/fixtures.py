"""Syntetiske testfiler: et minimalt georeferert OCAD-kart og en Purple Pen-løype.

Klubbens egne kart skal ikke ligge i et offentlig repo, og testene må kunne
kjøre hos andre. Derfor lages filene her i stedet, med kjente koordinater så
resultatet kan regnes ut for hånd.
"""
import struct

# Kartet: 1:10000, UTM 32N, origo (280000, 6700000), ingen rotasjon.
SCALE, EPSG, X0, Y0, ANGLE = 10000.0, 32632, 280000.0, 6700000.0, 0.0


def ocd_map(path, scale=SCALE, x0=X0, y0=Y0, angle=ANGLE, epsg=EPSG, extent=None):
    """Skriver en .ocd med parameterstrengen 1039 og eventuelt ett objekt.

    Uten extent har fila ingen objekter - skriptene leser da bare
    georefereringen. Med extent=(venstre, bunn, høyre, topp) i papir-mm får den
    ett flateobjekt med det omsluttende rektangelet, så kontrollen av poster
    utenfor kartet har noe å måle mot.
    """
    setup = ('\tm%.6f\tg50.0000\tr1\tx%.0f\ty%.0f\ta%.8f\td250.00\ti2032\te%d'
             % (scale, x0, y0, angle, epsg)).encode('cp1252') + b'\x00'
    header = bytearray(48)
    str_idx = len(header)                      # strengindeksblokk rett etter headeren
    block = bytearray(4 + 256 * 16)
    data_pos = str_idx + len(block)
    struct.pack_into('<I', block, 0, 0)        # ingen neste blokk
    struct.pack_into('<iiii', block, 4, data_pos, len(setup), 1039, 0)
    obj_idx = 0
    tail = b''
    if extent:
        obj_idx = data_pos + len(setup)
        oblock = bytearray(4 + 256 * 40)
        rec_pos = obj_idx + len(oblock)
        L, B, R, T = (int(round(v * 100)) << 8 for v in extent)
        struct.pack_into('<iiii', oblock, 4, L, B, R, T)
        struct.pack_into('<iii', oblock, 4 + 16, rec_pos, 0, 301000)
        oblock[4 + 28] = 3                     # flate
        oblock[4 + 30] = 1                     # normal, synlig
        rec = bytearray(56)
        struct.pack_into('<iB', rec, 0, 301000, 3)
        tail = bytes(oblock) + bytes(rec)
    struct.pack_into('<hBBhBBII', header, 0, 0x0CAD, 0, 0, 2018, 0, 0, 0, obj_idx)
    struct.pack_into('<I', header, 32, str_idx)
    with open(path, 'wb') as f:
        f.write(header); f.write(block); f.write(setup); f.write(tail)
    return path


# Omsluttende rektangel for testkartet: romslig rundt løype A.
EXTENT = (-50.0, -50.0, 150.0, 150.0)


PPEN = '''<?xml version="1.0" encoding="utf-8"?>
<course-scribe-event>
  <event id="1">
    <title>Testtrening</title>
    <map kind="OCAD" scale="10000" absolute-path="C:\\\\test\\\\{mapname}">{mapname}</map>
    <all-controls print-scale="10000" description-kind="symbols" />
  </event>
  <control id="1" kind="start"><location x="0" y="0" /></control>
  <control id="2" kind="normal"><code>31</code><location x="10" y="0" /></control>
  <control id="3" kind="normal"><code>32</code><location x="10" y="10" /></control>
  <control id="4" kind="finish"><location x="0" y="10" /></control>
  <course-control id="1" control="1"><next course-control="2" /></course-control>
  <course-control id="2" control="2"><next course-control="3" /></course-control>
  <course-control id="3" control="3"><next course-control="4" /></course-control>
  <course-control id="4" control="4" />
  <course id="1" kind="normal" order="1">
    <name>A</name>
    <first course-control="1" />
    <options print-scale="10000" />
  </course>
</course-scribe-event>
'''


def ppen_course(path, mapname='testkart.ocd', ppen=None):
    with open(path, 'w', encoding='utf-8') as f:
        f.write((ppen or PPEN).format(mapname=mapname))
    return path


# En løypefil uten løyper - Storasen 2026 var slik, og gikk rett gjennom.
PPEN_TOM = PPEN[:PPEN.index('  <course id="1"')] + '</course-scribe-event>\n'

# Løype A med post 32 flyttet 300 mm opp - 3 km utenfor testkartet.
PPEN_UTENFOR = PPEN.replace('<location x="10" y="10" />', '<location x="10" y="300" />')


# Fasit for løype A: postene ligger på 0/100/100+100/100 meter i kartplanet,
# altså 100 + 100 + 100 = 300 m strekklengde, og start i (280000, 6700000).
EXPECTED_LENGTH = 300
EXPECTED_START = (X0, Y0)


# Fasit fra virkeligheten: Herdla-kartet (1:4000, origo 278000/6721000, vinkel
# 6,1°) og to poster fra treningen 22.10.2026. Posisjonene er kontrollert mot
# kartet Livelox leser fra .ocd og mot en deltakers GPS-spor, der Livelox fant
# alle postene automatisk. Med feil fortegn på vinkelen havner de 100-250 m
# vestover - det er feilen denne fasiten skal fange.
HERDLA = dict(scale=4000.0, x0=278000.0, y0=6721000.0, angle=6.1, epsg=32632)
HERDLA_POSTER = {                 # papir-mm i .ppen -> UTM 32N, meter
    'S': ((8.30557, 299.856567), (278160.49, 6722189.10)),
    '38': ((-82.335144, 356.4899), (277824.05, 6722452.88)),
}
HERDLA_START_WGS84 = (4.9507069, 60.5741620)    # (lengdegrad, breddegrad)
