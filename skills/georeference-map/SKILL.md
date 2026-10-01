---
name: georeference-map
description: EXPERIMENTAL - work out the georeferencing of an OCAD map that has none, by matching lakes against OpenStreetMap or place names against Kartverket. Read the control results in this skill before trusting an answer. Bruk for ugeoreferert kart, georeferering og kartplassering.
---

# Georeferering av gamle o-kart

Et kart uten referansesystem kan ikke brukes i Livelox uten at noen drar det på
plass over et satellittbilde. Tanken her er å regne ut plasseringen i stedet:
finne rotasjonen og origo kartet mangler, ved å kjenne igjen ting som finnes
både i kartet og i åpne data. Skriptene skriver aldri i kartfila – de gir tall
til `Kart > Velg målestokk og referansesystem` i OCAD.

## Status: ikke til å stole på alene

Metoden er testet mot kart der fasiten er kjent (georefererte kart i AOLs
arkiv). **Vannflatematchingen mot OSM består ikke testen**: den finner 3–5
«treff» med 10–30 meters avvik på helt feil sted, fordi et o-kart har få store
vann og OSM har mange, og tilfeldige trillinger stemmer like godt som den
riktige. På Davanger, der fasiten er vinkel 0° og origo (287000, 6710000),
foreslo den vinkel −146° og origo (285179, 6697864).

Årsaken ligger i datagrunnlaget: under Davangers *riktige* georeferering
traff bare 3 av 16 vannflater i kartet et OSM-vann innenfor 60 m. OSMs
vanndekning på Askøy er for tynn, og kartets vannflater er delt opp og
inkluderer sjøen.

**Stedsnavn fungerer derimot.** Under riktig georeferering havner Davangers
navn `Skogatjørna` og `Sagvatnet` 47 og 78 meter fra Kartverkets punkter for de
samme vannene. Navn av typen `Vann` og `Tjern` er til å stole på; `Gard` og
`Navnegard` er det ikke – Kartverkets punkt for en gard ligger gjerne en
kilometer fra der navnet står på kartet.

Begrensningen er antallet: et kart må ha minst to–tre *vannavn* med god
avstand mellom seg. Fauskanger har bare to, 424 m fra hverandre, og da blir
vinkelen usikker med ±16°. Plasseringen blir riktig, vinkelen omtrentlig.

## Skriptene

`scripts/georef_names.py` – slår kartets tekstobjekter opp i Kartverkets
stedsnavn-API og finner rotasjon og origo av navnene som stemmer. Navn delt
over to linjer (`Skråmestø-` / `vatnet`) settes sammen igjen. API-et overser
kommune- og fylkesfiltre, så filtreringen skjer på svaret.

```
python3 georef_names.py kart.ocd --kommune Askøy
```

`scripts/georef_osm.py` – vannflatematching mot OpenStreetMap via Overpass.
Se advarselen over; bruk den bare som kontroll av et svar du har fra før.

## Hvis dette skal bli noe andre klubber kan bruke

Tre ting må på plass:

1. **Tettere vanndata.** Kartverkets N50 Innsjø (Geonorge, WFS eller nedlasting)
   har alle vann, ikke bare de OSM har fått med. Da kan formen på vannflatene
   brukes, ikke bare navnene, og kravet om navn på kartet forsvinner.
2. **En kontrolltest som kjøres automatisk.** Kjør metoden mot kart med kjent
   georeferering og krev at den treffer innenfor noen titalls meter før et
   svar presenteres. Uten det leverer den selvsikre og gale tall.
3. **Rasterkorrelasjon mot mapant.no** er trolig det som ville fungert best –
   mapant er laget av lidar over hele landet, og korrelasjon på kurve- eller
   vannbilder bruker hele kartflaten i stedet for noen få punkter. Det krever
   at kartet rasteriseres, som igjen krever symbolrendering.

Metoden er ellers kartverk-uavhengig: alt som gir koordinater til gjenkjennbare
objekter kan brukes som kilde.

## Uansett metode

Kontroller resultatet mot flyfoto i OCAD før kartet tas i bruk. Et kart som
ligger 200 meter feil ser riktig ut i seg selv, og feilen viser seg først når
postene havner i feil terreng i Livelox.
