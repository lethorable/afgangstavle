# rejseplanen_a – Home Assistant custom component

Overvåger linje A (DSB S-tog) fra Åmarken mod Hillerød.
Henter data direkte fra Rejseplanens HTML-endpoint – ingen API-nøgle nødvendig.

## Installation

1. Kopier mappen `custom_components/rejseplanen_a/` til din HA-instans:
   ```
   /config/custom_components/rejseplanen_a/
   ```

2. Tilføj til `configuration.yaml`:
   ```yaml
   sensor:
     - platform: rejseplanen_a
       scan_interval: 60
   ```

3. Genstart Home Assistant.

## Sensorer

| Entity ID | Beskrivelse | Eksempelværdi |
|---|---|---|
| `sensor.linje_a_naeste_afgang` | Planlagt afgangstid (HH:MM) | `10:31` |
| `sensor.linje_a_forsinkelse_minutter` | Forsinkelse i minutter | `7` |

### Attributter på `sensor.linje_a_naeste_afgang`

| Attribut | Beskrivelse |
|---|---|
| `planned_time` | Planlagt tid |
| `expected_time` | Forventet tid |
| `delay_minutes` | Forsinkelse |
| `destination` | Hillerød St. |
| `minutes_until` | Minutter til forventet afgang |
| `next_departures` | Liste med de næste 3 afgange |
| `last_update` | Tidspunkt for seneste datahentning |

## Automationer

Se `configuration_example.yaml` for eksempler på:
- Lys der skifter til **rødt** ved > 5 min forsinkelse
- Lys der skifter til **grønt** igen
- Push-notifikation til telefon

## Krav

Installeres automatisk via HA:
- `beautifulsoup4`
- `lxml`
