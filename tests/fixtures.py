"""Syntetiske testfiler: et minimalt georeferert OCAD-kart og en Purple Pen-løype.

Klubbens egne kart skal ikke ligge i et offentlig repo, og testene må kunne
kjøre hos andre. Derfor lages filene her i stedet, med kjente koordinater så
resultatet kan regnes ut for hånd.
"""
import struct

# Kartet: 1:10000, UTM 32N, origo (280000, 6700000), ingen rotasjon.
SCALE, EPSG, X0, Y0, ANGLE = 10000.0, 32632, 280000.0, 6700000.0, 0.0


def ocd_map(path):
    """Skriver en .ocd med bare det parameterstrengen 1039 trenger.

    Filen har ingen symboler eller objekter - skriptene leser kun
    georefereringen fra den.
    """
    setup = ('\tm%.6f\tg50.0000\tr1\tx%.0f\ty%.0f\ta%.8f\td250.00\ti2032\te%d'
             % (SCALE, X0, Y0, ANGLE, EPSG)).encode('cp1252') + b'\x00'
    header = bytearray(48)
    struct.pack_into('<hBBhBBII', header, 0, 0x0CAD, 0, 0, 2018, 0, 0, 0, 0)
    str_idx = len(header)                      # strengindeksblokk rett etter headeren
    block = bytearray(4 + 256 * 16)
    data_pos = str_idx + len(block)
    struct.pack_into('<I', block, 0, 0)        # ingen neste blokk
    struct.pack_into('<iiii', block, 4, data_pos, len(setup), 1039, 0)
    struct.pack_into('<I', header, 32, str_idx)
    with open(path, 'wb') as f:
        f.write(header); f.write(block); f.write(setup)
    return path


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


def ppen_course(path, mapname='testkart.ocd'):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(PPEN.format(mapname=mapname))
    return path


# Fasit for løype A: postene ligger på 0/100/100+100/100 meter i kartplanet,
# altså 100 + 100 + 100 = 300 m strekklengde, og start i (280000, 6700000).
EXPECTED_LENGTH = 300
EXPECTED_START = (X0, Y0)
