# Rejseplanen Linje A – Home Assistant custom component

Overvåger S-tog linje A fra **Åmarken mod Hillerød**.
Henter data direkte fra Rejseplanens HTML-endpoint – ingen API-nøgle nødvendig.

---

## Installation via HACS (anbefalet)

1. Sørg for at [HACS](https://hacs.xyz) er installeret i din Home Assistant.
2. Gå til **HACS → ⋮ → Custom repositories**.
3. Indsæt URL'en `https://github.com/lethorable/afgangstavle` og vælg kategori **Integration**.
4. Klik **Add** og søg derefter efter **Rejseplanen Linje A**.
5. Installér og **genstart Home Assistant**.

---

## Manuel installation

1. Download eller klon dette repo.
2. Kopier mappen `custom_components/rejseplanen_a/` til:
   ```
   /config/custom_components/rejseplanen_a/
   ```
3. **Genstart Home Assistant**.

---

## Konfiguration

Tilføj følgende til din `configuration.yaml`:

```yaml
sensor:
  - platform: rejseplanen_a
    scan_interval: 60   # sekunder mellem opdateringer (default: 60)
```

Genstart Home Assistant igen efter ændringen.

---

## Sensorer

| Entity ID | Beskrivelse | Eksempelværdi |
|---|---|---|
| `sensor.linje_a_naeste_afgang` | Planlagt afgangstid (HH:MM) | `10:31` |
| `sensor.linje_a_forsinkelse_minutter` | Forsinkelse i minutter | `7` |

### Attributter på `sensor.linje_a_naeste_afgang`

| Attribut | Beskrivelse |
|---|---|
| `planned_time` | Planlagt afgangstid |
| `expected_time` | Forventet afgangstid |
| `delay_minutes` | Forsinkelse i minutter |
| `minutes_until` | Minutter til forventet afgang |
| `destination` | Hillerød St. |
| `next_departures` | Liste med de næste 3 afgange |
| `last_update` | Tidspunkt for seneste datahentning |

---

## Statistik

Forsinkelsessensoren har `state_class: measurement`, så Home Assistant automatisk opbygger langtidsstatistik.
Tilføj et statistikkort i dit dashboard:

```yaml
type: statistics-graph
title: Linje A forsinkelse
entities:
  - sensor.linje_a_forsinkelse_minutter
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

Følgende Python-pakker bruges og installeres automatisk af Home Assistant:
- `beautifulsoup4`
- `lxml`
