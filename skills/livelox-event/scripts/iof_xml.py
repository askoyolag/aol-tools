"""IOF XML 3.0 CourseData fra et ferdig bygget arrangement.

Livelox' nettside georefererer ikke Purple Pen-filer: lastes en .ppen opp
direkte, havner postene i kartets papirkoordinater og må dras på plass for
hånd. En IOF XML-fil med `<Position lng lat>` plasseres derimot riktig med
én gang. Fila lages derfor alltid, så den kan lastes opp under *Løyper* i
Livelox når API-et ikke kan brukes - eller i andre programmer som leser IOF XML.
"""
import datetime as dt
from xml.sax.saxutils import escape, quoteattr

NS = 'http://www.orienteering.org/datastandard/3.0'


def course_data(ev, lonlat, creator='CourseImport'):
    """ev: arrangementet fra livelox_event.build; lonlat: {kode: (lng, lat)}."""
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<CourseData xmlns=%s iofVersion="3.0" createTime=%s creator=%s>'
           % (quoteattr(NS), quoteattr(now), quoteattr(creator)),
           '  <Event>', '    <Name>%s</Name>' % escape(ev['name']), '  </Event>',
           '  <RaceCourseData>']
    for c in ev['controls']:
        lng, lat = lonlat[c['code']]
        out += ['    <Control type=%s>' % quoteattr(c['type']),
                '      <Id>%s</Id>' % escape(c['code']),
                '      <Position lng="%.7f" lat="%.7f"/>' % (lng, lat),
                '    </Control>']
    for c in ev['courses']:
        out.append('    <Course>')
        out.append('      <Name>%s</Name>' % escape(c['name']))
        if c.get('length'):
            out.append('      <Length>%d</Length>' % round(c['length']))
        types = {x['code']: x['type'] for x in ev['controls']}
        for cc in c['controls']:
            out += ['      <CourseControl type=%s>' % quoteattr(types.get(cc['code'], 'Control')),
                    '        <Control>%s</Control>' % escape(cc['code']),
                    '      </CourseControl>']
        out.append('    </Course>')
    out += ['  </RaceCourseData>', '</CourseData>', '']
    return '\n'.join(out)
