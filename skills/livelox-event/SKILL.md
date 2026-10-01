---
name: livelox-event
description: Set up Livelox events for races and training runs — read Purple Pen (.ppen) courses, georeference them from the OCAD map, and build or upload a Livelox importable event. Use for Livelox, treningsløp, løypefiler and .ppen questions.
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
   første start), arrangørklubb. Klassifiser det som **trening**, ikke konkurranse –
   treninger er unntatt forsinket tilgang til ruter, så alle ser veivalgene med én gang.
2. **Kart:** last opp kartfila. Livelox leser OCAD- (`.ocd`) og Open Orienteering
   Mapper-filer, i tillegg til PNG/TIFF. Kartet må være georeferert; er det ikke det,
   plasseres det manuelt mot satellittbilde. Kartet skal være uten løyper og uten
   ramme, tittel og logoer.
3. **Løyper:** last opp `.ppen`-fila under `Courses`. Kontroller fanene *Courses*,
   *Controls* og *Preview* før du lagrer.
4. **Klasser:** svar ja når Livelox tilbyr å lage én klasse per løype. Hold deg på
   maks 10 klasser – det er kravet for at et klubbabonnement skal dekke treningen.
5. **Publiseringstid:** sett den til etter siste start.
6. Del lenken i Spond. Deltakerne laster opp spor selv – Livelox-appen, eller
   GPX/Garmin/Suunto/Polar-kobling i etterkant – og velger riktig klasse.

## Skriptene

`scripts/ppen.py` leser `.ppen`-fila: tittel, kartreferanse, målestokk, løyper med
ordnet postrekkefølge, postkoder og posisjoner. Koordinatene er i millimeter i
kartets papirkoordinatsystem, samme system som OCAD bruker.

`scripts/ocad_geo.py` henter georefereringen fra OCAD-kartet (parameterstreng
1039: målestokk, vinkel, origo, EPSG-kode) og regner om millimeter til projiserte
koordinater. Bruker parseren i `ocad-files`-skillen.

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
til disk så den kan kontrolleres. Med `--post` opprettes den importerbare
hendelsen, filene lastes opp, valideringen kjøres, og skriptet skriver ut
URL-en der løypeleggeren fullfører importen med ett klikk.

Kjører du samme løypefil på nytt, oppdateres arrangementet i stedet for at det
lages et nytt – id-en utledes av filnavnet, og skriptet sjekker først om Livelox
kjenner den fra før. Er importen alt fullført, går oppdateringen helt uten
nettleser (`PUT /importableEvents/{id}/import`). Navn og tidspunkt kan ikke
endres den veien; det må gjøres i Livelox.

Finner valideringen feil, stopper skriptet og skriver dem ut i stedet for å
sende løypeleggeren videre til en import som uansett ville blitt avvist.

`scripts/livelox_auth.py` håndterer innloggingen (OAuth2 Authorization Code med
PKCE). Kjør den én gang per maskin: nettleseren åpnes, løypeleggeren logger inn
i Livelox og godkjenner. Tokenet lagres i `~/.config/livelox/tokens.json` og
fornyes automatisk – refresh-token utløper ikke. Klient-id og redirect-URI kan
settes med `LIVELOX_CLIENT_ID` og `LIVELOX_REDIRECT_URI`.

## API-et (api.livelox.com)

- `POST /importableEvents` → `{id, liveloxImportEventUrl}`.
- `POST /importableEvents/{id}/files/{fileName}` for hver fil (eller én zip).
- `GET /importableEvents/{id}/validationErrors` før du sender brukeren videre.
- `PUT /importableEvents/{id}` + `PUT /importableEvents/{id}/import` oppdaterer et
  allerede importert arrangement **uten** omvei om nettleseren.
- Autorisering: OAuth2 med scope `events.import`. Livelox gir ikke klubber
  API-nøkkel, men regner et verktøy som dette som event management software og
  setter opp en klient-id mot en oppgitt redirect-URI. Avtales med
  info@livelox.com; ingen selvbetjent registrering. Utløpt token gir HTTP 403,
  og da fornyes det med refresh-tokenet.
- Kartet kan lastes opp som `.ocd` (eller `.oom`, `.kmz`) – de bærer
  georefereringen selv, og da skal `georeference` utelates. Rasterkart
  (PNG/TIFF/JPEG/GIF) trenger world-fil eller koordinatmapping.
- Klassifiseringen settes med `level`: `club` og `local` blir trening i
  Livelox, de øvrige blir konkurranse. Det er verdt å få riktig – treninger er
  unntatt forsinket tilgang til ruter.
- Dokumentasjon: https://www.livelox.com/Documentation/Api/EventIntegration

## Fallgruver

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
