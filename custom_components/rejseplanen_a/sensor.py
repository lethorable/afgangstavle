"""
Sensor: Rejseplanen Afgangstavle – generisk afgangsmonitor.

Opretter to sensorer pr. config entry:
  - sensor.<station>_linje_<x>_naeste_afgang       → planlagt afgangstid (HH:MM)
  - sensor.<station>_linje_<x>_forsinkelse_minutter → forsinkelse i hele minutter

Legacy YAML (bagudkompatibelt):
  sensor:
    - platform: rejseplanen_a
      scan_interval: 60
  → bevarer de originale Åmarken / Linje A / Hillerød sensorer.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import CONF_SCAN_INTERVAL
import homeassistant.helpers.config_validation as cv
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# ── Config-nøgler (deles med config_flow) ────────────────────────────────────

CONF_STATION_ID = "station_id"
CONF_STATION_NAME = "station_name"
CONF_LINE_FILTER = "line_filter"
CONF_DESTINATION_FILTER = "destination_filter"

# ── Legacy-standarder (YAML / Åmarken → Hillerød) ───────────────────────────

_LEGACY_STATION_ID = "8600763"
_LEGACY_STATION_NAME = "Åmarken St."
_LEGACY_LINE = "A"
_LEGACY_DESTINATION = "Hillerød"

# ── URL-template ─────────────────────────────────────────────────────────────

STBOARD_URL_TEMPLATE = (
    "https://webapp.rejseplanen.dk/bin/stboard.exe/mn"
    "?L=vs_rp4&input={station_id}&boardType=dep"
    "&productsFilter=1111111111111111"
    "&time=now&selectDate=today&maxJourneys=20&start=yes"
)

DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
    }
)


# ── Platform setup ────────────────────────────────────────────────────────────

async def async_setup_entry(hass, entry, async_add_entities):
    """Opsæt sensorer fra config entry (UI-flow)."""
    merged = {**entry.data, **entry.options}

    station_id = merged[CONF_STATION_ID]
    station_name = merged.get(CONF_STATION_NAME, station_id)
    line_filter = merged.get(CONF_LINE_FILTER, "").strip()
    destination_filter = merged.get(CONF_DESTINATION_FILTER, "").strip()
    scan_interval = timedelta(seconds=int(merged.get(CONF_SCAN_INTERVAL, 60)))

    coordinator = RejseplanenCoordinator(
        station_id=station_id,
        line_filter=line_filter,
        destination_filter=destination_filter,
        min_interval=scan_interval,
    )
    await hass.async_add_executor_job(coordinator.update)

    async_add_entities(
        [
            NextDepartureSensor(coordinator, station_id, station_name, line_filter),
            DelayMinutesSensor(coordinator, station_id, station_name, line_filter),
        ],
        update_before_add=False,
    )


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Legacy YAML-opsætning – bevarer originale Åmarken/Linje A/Hillerød sensorer."""
    scan_interval = config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    coordinator = RejseplanenCoordinator(
        station_id=_LEGACY_STATION_ID,
        line_filter=_LEGACY_LINE,
        destination_filter=_LEGACY_DESTINATION,
        min_interval=scan_interval,
    )
    coordinator.update()

    add_entities(
        [
            NextDepartureSensor(
                coordinator, _LEGACY_STATION_ID, _LEGACY_STATION_NAME, _LEGACY_LINE
            ),
            DelayMinutesSensor(
                coordinator, _LEGACY_STATION_ID, _LEGACY_STATION_NAME, _LEGACY_LINE
            ),
        ],
        update_before_add=True,
    )


# ── Coordinator ───────────────────────────────────────────────────────────────

class RejseplanenCoordinator:
    """Henter og parser afgangstavlen fra Rejseplanen."""

    def __init__(
        self,
        station_id: str,
        line_filter: str = "",
        destination_filter: str = "",
        min_interval: timedelta = DEFAULT_SCAN_INTERVAL,
    ):
        self.departures: list[dict] = []
        self.last_update: datetime | None = None
        self.error: str | None = None

        self._station_id = station_id
        self._line_filter = line_filter.upper()
        self._destination_filter = destination_filter
        self._min_interval = min_interval
        self._url = STBOARD_URL_TEMPLATE.format(station_id=station_id)

    def update(self):
        """Hent data – spring over hvis vi opdaterede for nylig."""
        if self.last_update and dt_util.now() - self.last_update < self._min_interval / 2:
            return
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; HomeAssistant/rejseplanen_a)"
            }
            resp = requests.get(self._url, headers=headers, timeout=10)
            resp.raise_for_status()
            self._parse(resp.text)
            self.error = None
            self.last_update = dt_util.now()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error(
                "Fejl ved hentning fra Rejseplanen (station %s): %s",
                self._station_id,
                exc,
            )
            self.error = str(exc)

    def _parse_time(self, raw: str) -> datetime | None:
        raw = raw.strip()
        m = re.match(r"(\d{1,2}):(\d{2})", raw)
        if not m:
            return None
        now = dt_util.now()
        dt = now.replace(
            hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0
        )
        if dt < now - timedelta(minutes=1):
            dt += timedelta(days=1)
        return dt

    def _parse(self, html: str):
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select("table tr")
        departures = []

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            planned_raw = cells[0].get_text(strip=True)
            expected_raw = cells[1].get_text(strip=True)
            line_raw = cells[2].get_text(strip=True).upper()
            bold = cells[4].find("span", class_="bold")
            destination_raw = bold.get_text(strip=True) if bold else cells[4].get_text(strip=True).split("-")[0].strip()

            if self._line_filter and self._line_filter not in line_raw:
                continue
            if self._destination_filter and self._destination_filter.lower() not in destination_raw.lower():
                continue

            planned_dt = self._parse_time(planned_raw)
            if planned_dt is None:
                continue

            expected_match = re.search(r"(\d{1,2}:\d{2})", expected_raw)
            expected_dt = (
                self._parse_time(expected_match.group(1))
                if expected_match
                else planned_dt
            )
            if expected_dt is None:
                expected_dt = planned_dt

            delay = max(0, int((expected_dt - planned_dt).total_seconds() // 60))
            departures.append(
                {
                    "planned": planned_dt,
                    "expected": expected_dt,
                    "delay_minutes": delay,
                    "destination": destination_raw,
                    "line": line_raw,
                }
            )

        now = dt_util.now()
        departures = [
            d for d in departures if d["expected"] >= now - timedelta(minutes=1)
        ]
        departures.sort(key=lambda d: d["planned"])
        self.departures = departures
        _LOGGER.debug(
            "Station %s: %d afgange (linje=%r, dest=%r)",
            self._station_id,
            len(departures),
            self._line_filter,
            self._destination_filter,
        )


# ── Hjælpefunktion til entity-slugs ──────────────────────────────────────────

def _make_slug(station_id: str, line_filter: str) -> str:
    slug = f"station_{station_id}"
    if line_filter:
        safe_line = re.sub(r"[^a-z0-9]", "_", line_filter.lower())
        slug += f"_linje_{safe_line}"
    return slug


# ── Sensorer ──────────────────────────────────────────────────────────────────

class NextDepartureSensor(SensorEntity):
    """Sensor: næste afgangstid."""

    _attr_icon = "mdi:train"

    def __init__(
        self,
        coordinator: RejseplanenCoordinator,
        station_id: str,
        station_name: str,
        line_filter: str,
    ):
        self._coordinator = coordinator
        slug = _make_slug(station_id, line_filter)
        self._attr_unique_id = f"rejseplanen_{slug}_naeste_afgang"
        label = station_name + (f" Linje {line_filter.upper()}" if line_filter else "")
        self._attr_name = f"{label} næste afgang"

    @property
    def native_value(self):
        deps = self._coordinator.departures
        return deps[0]["planned"].strftime("%H:%M") if deps else None

    @property
    def extra_state_attributes(self):
        deps = self._coordinator.departures
        if not deps:
            return {"error": self._coordinator.error}
        first = deps[0]
        minutes_until = max(
            0, int((first["expected"] - dt_util.now()).total_seconds() // 60)
        )
        return {
            "planned_time": first["planned"].strftime("%H:%M"),
            "expected_time": first["expected"].strftime("%H:%M"),
            "delay_minutes": first["delay_minutes"],
            "minutes_until": minutes_until,
            "destination": first["destination"],
            "line": first["line"],
            "next_departures": [
                {
                    "planned": d["planned"].strftime("%H:%M"),
                    "expected": d["expected"].strftime("%H:%M"),
                    "delay_minutes": d["delay_minutes"],
                    "destination": d["destination"],
                    "line": d["line"],
                }
                for d in deps[:3]
            ],
            "last_update": (
                self._coordinator.last_update.strftime("%H:%M:%S")
                if self._coordinator.last_update
                else None
            ),
        }

    def update(self):
        self._coordinator.update()


class DelayMinutesSensor(SensorEntity):
    """Sensor: forsinkelse i minutter for næste afgang."""

    _attr_icon = "mdi:clock-alert-outline"
    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: RejseplanenCoordinator,
        station_id: str,
        station_name: str,
        line_filter: str,
    ):
        self._coordinator = coordinator
        slug = _make_slug(station_id, line_filter)
        self._attr_unique_id = f"rejseplanen_{slug}_forsinkelse"
        label = station_name + (f" Linje {line_filter.upper()}" if line_filter else "")
        self._attr_name = f"{label} forsinkelse minutter"

    @property
    def native_value(self):
        deps = self._coordinator.departures
        return deps[0]["delay_minutes"] if deps else None

    def update(self):
        self._coordinator.update()
