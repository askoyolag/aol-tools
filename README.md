# aol-tools

Claude-plugin med kart- og løypeverktøy for Askøy orienteringslag.

- **OCAD-kartfiler** (`.ocd`) leses direkte – uten OCAD installert – med
  målestokk, georeferering, symboler, farger, trykkramme, blending og
  objektgeometri. Laget i forbindelse med arealberegning av skolekart.
- **Livelox og Purple Pen**: leser `.ppen`-løyper, georefererer dem fra
  OCAD-kartet og bygger arrangementet Livelox' import-API forventer.

Het tidligere `ocad-tools`.

## Installasjon i Claude Code / Cowork

```
/plugin marketplace add <url-til-dette-repoet>
/plugin install aol-tools@aol-kart
```

Eller lokalt, når repoet er klonet:

```
/plugin marketplace add /sti/til/aol-tools
/plugin install aol-tools@aol-kart
```

## Innhold

- `skills/ocad-files/SKILL.md` – filformatet, fallgruver og arbeidsmetode
- `skills/ocad-files/scripts/ocad.py` – minimal leser for `.ocd`
- `skills/ocad-files/scripts/ocad_print.py` – trykkramme, blending, trykt areal
- `skills/ocad-files/scripts/ocad_area.py` – kartlagt terrengareal
- `skills/livelox-event/SKILL.md` – oppsett av Livelox-arrangement, API-et og fallgruver
- `skills/livelox-event/scripts/ppen.py` – leser Purple Pen-løypefiler
- `skills/livelox-event/scripts/ocad_geo.py` – kartmillimeter → projiserte koordinater
- `skills/livelox-event/scripts/livelox_event.py` – bygger og laster opp Livelox-arrangement

`ocad-files` krever `numpy`, `scipy`, `Pillow`, `shapely` (og `pyproj` for
koordinater). `livelox-event` klarer seg med standardbiblioteket.
