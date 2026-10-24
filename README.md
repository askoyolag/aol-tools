# aol-tools

Kart- og løypeverktøy for orienteringsklubber, laget i Askøy orienteringslag.
Pakket som en Claude-plugin, men skriptene kan kjøres rett fra kommandolinjen
uten Claude. Alt er Python uten avhengigheter utover standardbiblioteket, med
unntak av arealberegningen.

Har du ikke Python på maskinen, er [uv](https://docs.astral.sh/uv/) den
enkleste veien – den henter riktig Python selv:

```powershell
winget install --id=astral-sh.uv -e                     # Windows
```
```bash
brew install uv                                         # macOS
curl -LsSf https://astral.sh/uv/install.sh | sh         # macOS og Linux
```

Deretter, uansett plattform:

```
uv run skills/livelox-event/scripts/livelox_event.py --help
```

Skriptene oppgir hvilken Python de trenger (3.11 eller nyere), så `uv run`
laster den ned hvis den mangler. Har du Python fra før, fungerer `python3`
like godt.

- **CourseImport** (`skills/livelox-event`) – setter opp Livelox-arrangementer
  fra Purple Pen-løyper (`.ppen`). Georefererer postene fra OCAD-kartet, lager
  en IOF XML-fil med ekte koordinater og laster opp alt til Livelox' import-API,
  så løypeleggeren bare fullfører med ett klikk. For OCAD Course Setting finnes
  OCADs egen Livelox-opplasting.
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
uv run skills/livelox-event/scripts/livelox_auth.py           # én gang per maskin
uv run skills/livelox-event/scripts/livelox_event.py "Trening mai.ppen" \
    --start 2026-05-12T18:00 --end 2026-05-12T21:00 \
    --name "Tirsdagstrening" --post
```

Kartet hentes fra fila `.ppen` peker på og sendes som `.ocd`; Livelox leser
georefereringen fra selve kartfila. Uten `--post` skrives arrangementet til en
JSON-fil så det kan kontrolleres først, sammen med en IOF XML-fil (`.xml`) med
ekte koordinater. Settes arrangementet opp for hånd i Livelox, er det XML-fila
som skal lastes opp under Løyper – Livelox plasserer ikke `.ppen` selv.

Publiseringstiden kan ikke settes via API-et. På treninger skal den være når
arrangementet starter, så alle kan se veivalgene med én gang – sett den under
Tilgangsbegrensning i Livelox etter importen. `--level club` (standard) gir
klassifiseringen trening i Livelox, som blant annet betyr at alle ser
veivalgene med én gang.

Forutsetninger: kartet må være georeferert, og løypene må ligge på det samme
kartet som `.ppen`-fila peker på.

### Tilgang

Autorisering skjer med OAuth2 (Authorization Code med PKCE) og scope
`events.import`. Hver løypelegger godkjenner med sin egen Livelox-konto, og
tokenet lagres lokalt i `~/.config/livelox/tokens.json`.

**Andre klubber trenger ingen egen registrering.** Klient-id-en `CourseImport`
er registrert hos Livelox for dette verktøyet, og Livelox foretrekker at alle
klubber bruker den samme – det er brukeren som gir tilgang, ikke klubben. Det
holder altså å installere verktøyet og kjøre `livelox_auth.py`.

Merk at opplastingen ikke er i drift ennå: per 24.10.2026 svarer Livelox 403 på
alle kall mot `/importableEvents` selv med gyldig token og riktig scope. Saken
er meldt til Livelox. Fram til den er løst lager skriptet en IOF XML-fil som
lastes opp manuelt under Løyper.

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
uv run python -m unittest discover -s tests
```

Testene lager sine egne kart- og løypefiler og kjører hele opplastingen mot en
etterligning av Livelox-API-et, så de krever verken klubbkart eller nettilgang.

## Lisens

MIT. Bruk det, endre det, del det videre.
