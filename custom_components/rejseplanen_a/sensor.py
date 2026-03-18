"""
Sensor: Rejseplanen Linje A – Åmarken → Hillerød

Henter afgangstider direkte fra Rejseplanens HTML-endpoint (ingen API-nøgle).
Opretter to sensorer:
  - sensor.linje_a_naeste_afgang       → tidspunkt for næste afgang (HH:MM)
  - sensor.linje_a_forsinkelse_minutter → forsinkelse i minutter (0 = til tiden)

Attributter på naeste_afgang-sensoren:
  - planned_time     – planlagt afgangstid
  - expected_time    – forventet afgangstid (= planned hvis ingen forsinkelse)
  - delay_minutes    – forsinkelse i hele minutter
  - destination      – "Hillerød St."
  - next_departures  – liste med de næste 3 afgange (planned, expected, delay)

Tilføj til configuration.yaml:
  sensor:
    - platform: rejseplanen_a
      scan_interval: 60   # sekunder mellem opdateringer (default: 60)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorEntity,
)
from homeassistant.const import CONF_SCAN_INTERVAL
import homeassistant.helpers.config_validation as cv
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Rejseplanens HTML-stboard for Åmarken St. (station-id 8600763 = S-tog Åmarken)
# productsFilter=0000100000000000 → kun S-tog
STBOARD_URL = (
    "https://webapp.rejseplanen.dk/bin/stboard.exe/mn"
    "?L=vs_rp4&input=8600763&boardType=dep"
    "&productsFilter=0000100000000000"
    "&time=now&selectDate=today&maxJourneys=20&start=yes"
)

DESTINATION = "Hillerød St."
DELAY_THRESHOLD = 5  # minutter

DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
    }
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Opsæt sensorer."""
    scan_interval = config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    coordinator = RejseplanenCoordinator()
    coordinator.update()

    add_entities(
        [
            NextDepartureSensor(coordinator),
            DelayMinutesSensor(coordinator),
        ],
        update_before_add=True,
    )


class RejseplanenCoordinator:
    """Henter og parser afgangstavlen fra Rejseplanen."""

    def __init__(self):
        self.departures: list[dict] = []
        self.last_update: datetime | None = None
        self.error: str | None = None

    def update(self):
        """Hent og parser HTML fra Rejseplanen."""
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; HomeAssistant/rejseplanen_a)"
                )
            }
            resp = requests.get(STBOARD_URL, headers=headers, timeout=10)
            resp.raise_for_status()
            self._parse(resp.text)
            self.error = None
            self.last_update = dt_util.now()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Fejl ved hentning fra Rejseplanen: %s", exc)
            self.error = str(exc)

    def _parse_time(self, raw: str) -> datetime | None:
        """Parser 'HH:MM' til et datetime-objekt for i dag (eller i morgen hvis fortid)."""
        raw = raw.strip()
        m = re.match(r"(\d{1,2}):(\d{2})", raw)
        if not m:
            return None
        now = dt_util.now()
        dt = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if dt < now - timedelta(minutes=1):
            dt += timedelta(days=1)
        return dt

    def _parse(self, html: str):
        """Parse HTML og udtræk afgange mod Hillerød."""
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select("table tr")

        departures = []
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            # Kolonner: Tid | Forventet | Linje | Fra | Mod
            planned_raw = cells[0].get_text(strip=True)
            expected_raw = cells[1].get_text(strip=True)
            line_raw = cells[2].get_text(strip=True)
            destination_raw = cells[4].get_text(strip=True)

            # Kun linje A mod Hillerød
            if "A" not in line_raw:
                continue
            if "Hillerød" not in destination_raw:
                continue

            planned_dt = self._parse_time(planned_raw)
            if planned_dt is None:
                continue

            # "Forventet" kan være tom (= til tiden) eller "ca. HH:MM"
            expected_match = re.search(r"(\d{1,2}:\d{2})", expected_raw)
            if expected_match:
                expected_dt = self._parse_time(expected_match.group(1))
            else:
                expected_dt = planned_dt

            if expected_dt is None:
                expected_dt = planned_dt

            delay = max(0, int((expected_dt - planned_dt).total_seconds() // 60))

            departures.append(
                {
                    "planned": planned_dt,
                    "expected": expected_dt,
                    "delay_minutes": delay,
                    "destination": DESTINATION,
                }
            )

        # Sorter og gem kun fremtidige afgange
        now = dt_util.now()
        departures = [d for d in departures if d["expected"] >= now - timedelta(minutes=1)]
        departures.sort(key=lambda d: d["planned"])
        self.departures = departures
        _LOGGER.debug("Fandt %d afgange mod Hillerød", len(departures))


class NextDepartureSensor(SensorEntity):
    """Sensor: næste afgang mod Hillerød."""

    _attr_name = "Linje A næste afgang"
    _attr_unique_id = "rejseplanen_a_naeste_afgang"
    _attr_icon = "mdi:train"

    def __init__(self, coordinator: RejseplanenCoordinator):
        self._coordinator = coordinator

    @property
    def native_value(self):
        deps = self._coordinator.departures
        if not deps:
            return None
        return deps[0]["planned"].strftime("%H:%M")

    @property
    def extra_state_attributes(self):
        deps = self._coordinator.departures
        if not deps:
            return {"error": self._coordinator.error}

        next3 = []
        for d in deps[:3]:
            next3.append(
                {
                    "planned": d["planned"].strftime("%H:%M"),
                    "expected": d["expected"].strftime("%H:%M"),
                    "delay_minutes": d["delay_minutes"],
                }
            )

        first = deps[0]
        return {
            "planned_time": first["planned"].strftime("%H:%M"),
            "expected_time": first["expected"].strftime("%H:%M"),
            "delay_minutes": first["delay_minutes"],
            "destination": first["destination"],
            "next_departures": next3,
            "last_update": (
                self._coordinator.last_update.strftime("%H:%M:%S")
                if self._coordinator.last_update
                else None
            ),
        }

    def update(self):
        self._coordinator.update()


class DelayMinutesSensor(SensorEntity):
    """Sensor: forsinkelse i minutter for næste afgang mod Hillerød."""

    _attr_name = "Linje A forsinkelse minutter"
    _attr_unique_id = "rejseplanen_a_forsinkelse"
    _attr_icon = "mdi:clock-alert-outline"
    _attr_native_unit_of_measurement = "min"

    def __init__(self, coordinator: RejseplanenCoordinator):
        self._coordinator = coordinator

    @property
    def native_value(self):
        deps = self._coordinator.departures
        if not deps:
            return None
        return deps[0]["delay_minutes"]

    def update(self):
        self._coordinator.update()
