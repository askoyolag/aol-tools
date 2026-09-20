# -*- coding: utf-8 -*-
"""Hent målestokk og ekvidistanse fra karttekstene i .ocd-filer."""
import re
from ocad import OcadFile

SC = re.compile(r'[Mm][åa]lestokk\D{0,4}1\s*[:/]\s*#?\s*([\d\s]{3,7})')
EK = re.compile(r'[Ee]kvidistanse\D{0,3}#?\s*([\d]+(?:[.,]\d+)?)\s*(?:m|meter)', re.I)

def from_text(*paths):
    scale = ekv = None
    for p in paths:
        if not p: continue
        try: o = OcadFile(p)
        except Exception: continue
        for ob in o.objects():
            t = ob.get('text', '') or ''
            if not t: continue
            t = ' '.join(t.split())
            if scale is None:
                m = SC.search(t)
                if m:
                    v = m.group(1).replace(' ', '')
                    if v.isdigit() and 200 <= int(v) <= 50000: scale = int(v)
            if ekv is None:
                m = EK.search(t)
                if m: ekv = m.group(1).replace('.', ',')
        if scale and ekv: break
    return scale, ekv
