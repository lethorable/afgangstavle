# Rejseplanen Afgangstavle – Home Assistant custom component

Overvåger afgange fra en valgfri station i det danske offentlige transportsystem.
Henter data direkte fra Rejseplanens HTML-endpoint – ingen API-nøgle nødvendig.

Understøtter S-tog, regionaltog, metro og bus.

---

## Installation

### Via HACS (anbefalet)

1. Sørg for at [HACS](https://hacs.xyz) er installeret i din Home Assistant.
2. Gå til **HACS → ⋮ → Custom repositories**.
3. Indsæt `https://github.com/lethorable/afgangstavle` og vælg kategori **Integration**.
4. Klik **Add**, søg efter **Rejseplanen Afgangstavle** og installér.
5. Genstart Home Assistant.

### Manuel installation

1. Download eller klon dette repo.
2. Kopier mappen `custom_components/rejseplanen_a/` til:
   ```
   /config/custom_components/rejseplanen_a/
   ```
3. Genstart Home Assistant.

---

## Opsætning

Efter installation opsættes integrationen via Home Assistants UI:

1. Gå til **Indstillinger → Enheder og tjenester → Tilføj integration**.
2. Søg efter **Rejseplanen Afgangstavle**.
3. **Søg station** — skriv et stationsnavn, f.eks. `Nørreport` eller `Åmarken`.
4. **Vælg station** — vælg den ønskede station i dropdown'en. Stationer med og uden "St." kan optræde separat (f.eks. er `Ryparken` et busstop og `Ryparken St.` en S-togsstation).
5. **Vælg linje** — dropdown med de linjer der aktuelt kører fra stationen (S-tog, bus, metro, regionaltog). Vælg en specifik linje eller *Alle linjer*.
6. **Vælg destination** — dropdown med de destinationer der hører til den valgte linje. Vælg en specifik destination eller *Alle destinationer*. Angiv desuden opdateringsinterval i sekunder (standard: 60).
7. Klik **Send**. Sensorerne er klar.

Linjer og destinationer hentes live fra stationens afgangstavle — du kan kun vælge kombinationer der faktisk eksisterer.

Du kan tilføje flere stationer ved at gentage processen.

### Ændring af indstillinger

Klik **Konfigurér** på integrationskortet under **Indstillinger → Enheder og tjenester**. Her kan du ændre linje, destination og opdateringsinterval. Stationen kan ikke ændres — slet og opret en ny entry i stedet.

---

## Sensorer

For hver opsætning oprettes to sensorer:

| Entity ID | Beskrivelse | Eksempelværdi |
|---|---|---|
| `sensor.<station>_linje_<x>_naeste_afgang` | Planlagt afgangstid (HH:MM) | `10:31` |
| `sensor.<station>_linje_<x>_forsinkelse_minutter` | Forsinkelse i minutter | `7` |

### Attributter på næste-afgang-sensoren

| Attribut | Beskrivelse |
|---|---|
| `planned_time` | Planlagt afgangstid |
| `expected_time` | Forventet afgangstid |
| `delay_minutes` | Forsinkelse i minutter |
| `minutes_until` | Minutter til forventet afgang |
| `line` | Linjenavn |
| `destination` | Destination |
| `next_departures` | Liste med de næste 3 afgange |
| `last_update` | Tidspunkt for seneste datahentning |

---

## Statistik

Forsinkelsessensoren gemmer automatisk langtidsstatistik i Home Assistant (`state_class: measurement`). Tilføj et statistikkort i dit dashboard:

```yaml
type: statistics-graph
title: Forsinkelse
entities:
  - sensor.<din_sensor>_forsinkelse_minutter
days_to_show: 30
stat_types:
  - mean
  - max
```

---

## Automationer

Se [`configuration_example.yaml`](configuration_example.yaml) for eksempler på:
- Lys der skifter til **rødt** ved > 5 min forsinkelse
- Lys der skifter til **grønt** igen når toget kører til tiden
- Push-notifikation til telefon

---

## Krav

- Home Assistant 2023.1 eller nyere
- `beautifulsoup4` (installeres automatisk)

Ingen API-nøgle, ingen cloud-afhængighed, ingen lxml — kun Pythons built-in HTML-parser.
