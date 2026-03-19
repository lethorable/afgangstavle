# Rejseplanen Afgangstavle – Home Assistant custom component

Overvåger afgange fra en valgfri station i det danske offentlige transportsystem.
Henter data direkte fra Rejseplanens HTML-endpoint – ingen API-nøgle nødvendig.

Understøtter S-tog, regionaltog, metro og bus.

---

## Installation via HACS (anbefalet)

1. Sørg for at [HACS](https://hacs.xyz) er installeret i din Home Assistant.
2. Gå til **HACS → ⋮ → Custom repositories**.
3. Indsæt `https://github.com/lethorable/afgangstavle` og vælg kategori **Integration**.
4. Klik **Add**, søg efter **Rejseplanen Afgangstavle** og installér.
5. Genstart Home Assistant.

---

## Manuel installation

1. Download eller klon dette repo.
2. Kopier mappen `custom_components/rejseplanen_a/` til:
   ```
   /config/custom_components/rejseplanen_a/
   ```
3. Genstart Home Assistant.

---

## Opsætning via UI

1. Gå til **Indstillinger → Enheder og tjenester → Tilføj integration**.
2. Søg efter **Rejseplanen Afgangstavle**.
3. **Trin 1 – Søg station:** Skriv et stationsnavn (f.eks. `Nørreport` eller `Åmarken`).
4. **Trin 2 – Vælg station:** Vælg station fra dropdown-listen.
5. **Trin 3 – Vælg linje:** Dropdown med de linjer der aktuelt kører fra stationen, eller vælg *Alle linjer*.
6. **Trin 4 – Vælg destination:** Dropdown med destinationer for den valgte linje (eller alle), samt opdateringsinterval i sekunder.
7. Klik **Send**. Sensorerne er klar.

Linjer og destinationer hentes live fra stationens afgangstavle — du kan kun vælge kombinationer der faktisk eksisterer.

Du kan tilføje flere stationer ved at gentage processen.

Vil du ændre linje, destination eller interval efterfølgende, klik **Konfigurér** på integrationskortet.

---

## Legacy-installation via configuration.yaml

Bevaret for bagudkompatibilitet. Opsætter de originale Åmarken → Hillerød / Linje A sensorer:

```yaml
sensor:
  - platform: rejseplanen_a
    scan_interval: 60
```

Genstart Home Assistant efter ændringen.

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

Forsinkelsessensoren gemmer automatisk langtidsstatistik i Home Assistant.
Tilføj et statistikkort i dit dashboard:

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

Følgende Python-pakke installeres automatisk af Home Assistant:
- `beautifulsoup4`
