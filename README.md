# aol-tools

Kart- og løypeverktøy for orienteringsklubber, laget i Askøy orienteringslag.
Pakket som en Claude-plugin, men skriptene kan kjøres rett fra kommandolinjen
uten Claude. Alt er Python uten avhengigheter utover standardbiblioteket, med
unntak av arealberegningen.

- **CourseImport** (`skills/livelox-event`) – setter opp Livelox-arrangementer
  fra løypefiler. Leser Purple Pen (`.ppen`) eller OCAD Course Setting,
  georefererer postene fra kartet og laster opp alt til Livelox' import-API, så
  løypeleggeren bare fullfører med ett klikk.
- **ocad-files** – leser og måler OCAD-kartfiler (`.ocd`) direkte, uten OCAD
  installert: målestokk, georeferering, symboler, farger, trykkramme, blending
  og kartlagt areal.
- **georeference-map** – *eksperimentell.* Forsøker å finne georefereringen til
  gamle kart ved å matche vann mot OpenStreetMap eller stedsnavn mot Kartverket.
  Les kontrollresultatene i skillens SKILL.md før du stoler på et svar.

## CourseImport

Et treningsløp i Livelox krever arrangement, kart, løyper og klasser. Det tar
5–10 minutter å klikke seg gjennom hver gang. CourseImport gjør alt unntatt
selve import-klikket:

```
python3 skills/livelox-event/scripts/livelox_auth.py          # én gang per maskin
python3 skills/livelox-event/scripts/livelox_event.py "Trening mai.ppen" \
    --start 2026-05-12T18:00 --end 2026-05-12T21:00 \
    --name "Tirsdagstrening" --post
```

Kartet hentes fra fila `.ppen` peker på og sendes som `.ocd`; Livelox leser
georefereringen fra selve kartfila. Uten `--post` skrives arrangementet til en
JSON-fil så det kan kontrolleres først. `--level club` (standard) gir
klassifiseringen trening i Livelox, som blant annet betyr at alle ser
veivalgene med én gang.

Forutsetninger: kartet må være georeferert, og løypene må ligge på det samme
kartet som `.ppen`-fila peker på.

### Tilgang

Opplasting krever at Livelox har registrert verktøyet. Autorisering skjer med
OAuth2 (Authorization Code med PKCE) og scope `events.import` – hver løypelegger
godkjenner med sin egen Livelox-konto, og tokenet lagres lokalt i
`~/.config/livelox/tokens.json`. Klient-id og redirect-URI settes med
`LIVELOX_CLIENT_ID` og `LIVELOX_REDIRECT_URI`.

Skal klubben din bruke dette, ta kontakt med info@livelox.com om tilgang, eller
med oss – det kan hende samme registrering kan dekke flere klubber.

## Bruk som Claude-plugin

```
/plugin marketplace add https://github.com/askoyolag/aol-tools
/plugin install aol-tools@aol-kart
```

Da kan du be Claude om ting som «sett opp Livelox for treningen på
Brenneklubben neste tirsdag» eller «hvor stort areal dekker dette kartet», og
skillene forklarer resten.

## Testing

```
python3 -m unittest discover -s tests
```

Testene lager sine egne kart- og løypefiler og kjører hele opplastingen mot en
etterligning av Livelox-API-et, så de krever verken klubbkart eller nettilgang.

## Lisens

MIT. Bruk det, endre det, del det videre.
