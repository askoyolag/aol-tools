---
name: livelox-event
description: Set up Livelox events for races and training runs — read Purple Pen (.ppen) courses, georeference them from the OCAD map, and build or upload a Livelox importable event. Use for Livelox, treningsløp, løyper, løypefiler, .ppen and course setting questions.
---

# Livelox-arrangement fra løypefiler

Livelox trenger fire ting for at deltakerne skal kunne legge inn sporene sine:
et **arrangement** (navn, tidsrom, arrangør), et **kart** (georeferert), **løyper**
og **klasser**. Tidtaking er ikke nødvendig – uten resultatliste laster hver
enkelt opp sitt eget GPS-spor og velger klasse selv.

## To arbeidsflyter

**Løp med OCAD Course Setting.** Bruk `Course setting > Upload to Livelox…` i
OCAD 2018+. OCAD rasteriserer kartet til PNG med world-fil, eksporterer
løypetrykk som SVG og løypedata som IOF XML, og laster alt opp i én operasjon.
Første gang åpnes nettleseren for å opprette arrangementet; etterpå velger du
`Update existing event`, som går uten nettleser. Er løpet i Eventor, opprett
Livelox-koblingen derfra først – da følger klasser, startlister og resultater med.

**Treningsløp med Purple Pen.** Purple Pen har ingen Livelox-eksport, men
Livelox leser `.ppen` direkte. Arrangementet opprettes fritt i Livelox
(`Manage > Event > Add an event`) – det krever verken Eventor eller abonnement.

## Manuell oppskrift for treningsløp

1. **Opprett arrangementet** i Livelox: navn, start- og sluttid (sett starttid til
   første start), arrangørklubb. AOL bruker navneformen «Trening DD.MM.ÅÅÅÅ».
   Livelox setter klokkeslett feil om du skriver i et felt som alt har en
   verdi – kontroller start og slutt før du lagrer. Klassifiser det som **trening**, ikke konkurranse –
   treninger er unntatt forsinket tilgang til ruter, så alle ser veivalgene med én gang.
2. **Kart:** last opp kartfila. Livelox leser OCAD- (`.ocd`) og Open Orienteering
   Mapper-filer, i tillegg til PNG/TIFF. Kartet må være georeferert; er det ikke det,
   plasseres det manuelt mot satellittbilde. Kartet skal være uten løyper og uten
   ramme, tittel og logoer.
3. **Løyper:** last opp **IOF XML-fila** som `livelox_event.py` lager
   (`livelox-<id>.xml`), ikke `.ppen`-fila. Livelox' nettside georefererer ikke
   Purple Pen: en `.ppen` havner i papirkoordinater og må dras på plass post for
   post, mens XML-fila har ekte koordinater og havner riktig med én gang. Meldes
   det at poster ligger utenfor kartet, er noe galt med georefereringen – ikke
   dra dem på plass, finn feilen. Kontroller fanene *Løyper*, *Poster* og
   *Forhåndsvisning* før du lagrer.
4. **Klasser:** svar ja når Livelox tilbyr å lage én klasse per løype. Hold deg på
   maks 10 klasser – det er kravet for at et klubbabonnement skal dekke treningen.
5. **Publiseringstid:** på treninger skal den være **når arrangementet starter**
   (første start), ikke når siste deltaker starter, som er Livelox' standardvalg.
   Det står under *Tidspunkt for publisering* når arrangementet opprettes, og
   under *Tilgangsbegrensning* etterpå. Løp med påmelding og startliste er
   annerledes – der skal ingen se løypene før siste start.
6. Del lenken i Spond. Deltakerne laster opp spor selv – Livelox-appen, eller
   GPX/Garmin/Suunto/Polar-kobling i etterkant – og velger riktig klasse.

## Skriptene

`scripts/ppen.py` leser `.ppen`-fila: tittel, kartreferanse, målestokk, løyper med
ordnet postrekkefølge, postkoder og posisjoner. Koordinatene er i millimeter i
kartets papirkoordinatsystem, samme system som OCAD bruker.

`scripts/ocad_geo.py` henter georefereringen fra OCAD-kartet (parameterstreng
1039: målestokk, vinkel, origo, EPSG-kode) og regner om millimeter til projiserte
koordinater, og videre til lengde- og breddegrad for UTM-systemene. Bruker
parseren i `ocad-files`-skillen. **OCADs vinkel er positiv med klokka**, så
papirkoordinatene roteres med `-vinkel`. Fram til 24.10.2026 var fortegnet feil,
og postene på roterte kart havnet langt unna (100–250 m på Herdla). Testen
`TestRotasjon` holder fast ved fasiten fra Herdla.

`scripts/iof_xml.py` skriver løypene som IOF XML 3.0 (`CourseData`) med
`<Position lng lat>` for hver post. `livelox_event.py` lager fila automatisk
ved siden av JSON-fila; det er den som lastes opp ved manuelt oppsett i Livelox,
og den kan leses av andre programmer som forstår IOF XML.

`scripts/livelox_event.py` setter sammen et *importable event object* slik
Livelox' integrasjons-API vil ha det, og laster opp OCAD-kartet sammen med
løypene:

```
python3 livelox_event.py "Trening mai 2026.ppen" \
    --start 2026-05-12T18:00 --end 2026-05-12T21:00 \
    --name "Tirsdagstrening Brenneklubben" [--post]
```

Kartet hentes fra fila `.ppen` peker på; `--map` overstyrer, `--no-map` dropper
opplastingen når kartet alt ligger i Livelox. Uten `--post` skrives JSON-fila
og IOF XML-fila til disk (i `--out`, som lages om den mangler) så de kan
kontrolleres eller brukes til manuelt oppsett. Med `--post` opprettes den importerbare
hendelsen, filene lastes opp, valideringen kjøres, og skriptet skriver ut
URL-en der løypeleggeren fullfører importen med ett klikk.

Kjører du samme løypefil på nytt, oppdateres arrangementet i stedet for at det
lages et nytt – id-en utledes av filnavnet, og skriptet sjekker først om Livelox
kjenner den fra før. Er importen alt fullført, går oppdateringen helt uten
nettleser (`PUT /importableEvents/{id}/import`). Navn og tidspunkt kan ikke
endres den veien; det må gjøres i Livelox.

Finner valideringen feil, stopper skriptet og skriver dem ut i stedet for å
sende løypeleggeren videre til en import som uansett ville blitt avvist.

Publiseringstiden kan ikke settes via API-et – det importerbare objektet har
ikke noe felt for den. Etter importen må den settes i Livelox, og skriptet
minner om det på treninger (`--level club`/`local`).

`scripts/livelox_auth.py` håndterer innloggingen (OAuth2 Authorization Code med
PKCE). Kjør den én gang per maskin: nettleseren åpnes, løypeleggeren logger inn
i Livelox og godkjenner. Tokenet lagres i `~/.config/livelox/tokens.json`,
fornyes før det går ut, og refresh-tokenet utløper ikke. `--status` viser om
maskinen er innlogget, `--logout` glemmer tokenet.

Klient-id-en er `CourseImport`, registrert hos Livelox og ment å brukes av alle
klubber – Livelox foretrekker én klient framfor én per klubb. Redirect-URI-en er
ikke forhåndsregistrert: den sendes med til samtykkesiden, så skriptet binder en
ledig port og bygger adressen av den (RFC 8252). `LIVELOX_CLIENT_ID` og
`LIVELOX_REDIRECT_URI` overstyrer begge om det skulle trengs.

## API-et (api.livelox.com)

- `POST /importableEvents` → `{id, liveloxImportEventUrl}`.
- `POST /importableEvents/{id}/files/{fileName}` for hver fil (eller én zip).
- `GET /importableEvents/{id}/validationErrors` før du sender brukeren videre.
- `PUT /importableEvents/{id}` + `PUT /importableEvents/{id}/import` oppdaterer et
  allerede importert arrangement **uten** omvei om nettleseren.
- Autorisering: OAuth2 med scope `events.import`. Livelox gir ikke klubber
  API-nøkkel, men regner et verktøy som dette som event management software.
  Klient-id-en `CourseImport` er på plass; ingen selvbetjent registrering, nye
  klienter avtales med info@livelox.com. Utløpt token gir HTTP 403, og da
  fornyes det med refresh-tokenet.
- **Uavklart (24.10.2026):** alle kall mot `/importableEvents` svarer 403 med
  tom kropp, også rett etter ny innlogging, mens samme token godtas av
  `/events/external/{id}` (400 «Not enough parameters set») og manglende token
  gir 401 om scopet. Tokenet er altså gyldig med riktig scope, men ikke
  autorisert for importerbare arrangementer. Spørsmål sendt til Livelox; inntil
  det er løst er manuell opplasting av IOF XML-fila veien.
- Kartet kan lastes opp som `.ocd` (eller `.oom`, `.kmz`) – de bærer
  georefereringen selv, og da skal `georeference` utelates. Rasterkart
  (PNG/TIFF/JPEG/GIF) trenger world-fil eller koordinatmapping.
- Klassifiseringen settes med `level`: `club` og `local` blir trening i
  Livelox, de øvrige blir konkurranse. Det er verdt å få riktig – treninger er
  unntatt forsinket tilgang til ruter.
- Dokumentasjon: https://www.livelox.com/Documentation/Api/EventIntegration

## Fallgruver

- **Kontroller posisjonene, ikke bare at fila bygger.** Livelox' melding om
  poster utenfor kartet, eller en deltakers GPS-spor som ikke treffer postene, er
  tegn på feil georeferering.
- **OCAD Course Setting:** dette verktøyet leser ikke løyper fra `.ocd`. Bruk
  OCADs egen `Upload to Livelox`, eller eksporter IOF XML 3.0 fra OCAD – den er
  georeferert når kartet er det.
- **Ugeoreferert kart** gir ingen posisjoner. Sjekk `realworld`-flagget og EPSG-koden
  i OCAD-oppsettet før du lager JSON – skriptet stopper ellers.
- Purple Pen-filer peker på kartet med absolutt Windows-sti. Skriptet leter også
  etter kartfila ved siden av `.ppen`-fila; ellers oppgi `--ocd`.
- Poster med lik kode i flere løyper er samme post i Livelox. Start og mål får
  kodene `S` og `F` når Purple Pen ikke har egne koder.
- **PDF-kart i Purple Pen** kan ikke georefereres. Peker prosjektet på en PDF,
  oppgi OCAD-kartet med `--ocd`, eller sett opp arrangementet manuelt.
- Et token gjelder brukeren som godkjente det. Importen havner på den
  Livelox-kontoen løypeleggeren logget inn med, ikke på klubben som sådan.
- Uten løypetrykk (SVG/PDF) tegner Livelox strekene selv ut fra postposisjonene –
  uten kuttede ringer og forbudte områder.
- Poengløp (`kind="score"` i Purple Pen) må settes til *Rogaining* på klassene i
  Livelox; last da opp bare poster, ingen løyper.
- I Norge dekker ikke forbundet de avanserte funksjonene. Uten klubbabonnement
  (fra 3 500 kr/år) må den enkelte ha Premium for å sammenligne flere ruter.
