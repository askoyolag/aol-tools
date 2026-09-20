# ocad-tools

Claude-plugin for å lese og måle OCAD-kartfiler (`.ocd`) direkte – uten OCAD
installert. Inneholder en skill med binærspesifikasjonen for filformatet, og
en Python-parser som leser målestokk, georeferering, symboler, farger,
trykkramme, blending og objektgeometri.

Laget for Askøy orienteringslag i forbindelse med arealberegning av skolekart.

## Installasjon i Claude Code / Cowork

```
/plugin marketplace add <url-til-dette-repoet>
/plugin install ocad-tools@aol-kart
```

Eller lokalt, når repoet er klonet:

```
/plugin marketplace add /sti/til/ocad-tools
/plugin install ocad-tools@aol-kart
```

## Innhold

- `skills/ocad-files/SKILL.md` – filformatet, fallgruver og arbeidsmetode
- `skills/ocad-files/scripts/ocad.py` – minimal leser for `.ocd`
- `skills/ocad-files/scripts/ocad_print.py` – trykkramme, blending, trykt areal
- `skills/ocad-files/scripts/ocad_area.py` – kartlagt terrengareal

Krever `numpy`, `scipy`, `Pillow`, `shapely` (og `pyproj` for koordinater).
