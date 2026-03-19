"""Config flow for Rejseplanen Afgangstavle."""

from __future__ import annotations

import json
import logging
import re

import requests
from bs4 import BeautifulSoup
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

_LOGGER = logging.getLogger(__name__)

DOMAIN = "rejseplanen_a"
DEFAULT_SCAN_INTERVAL = 60
CONF_STATION_ID = "station_id"
CONF_STATION_NAME = "station_name"
CONF_LINE_FILTER = "line_filter"
CONF_DESTINATION_FILTER = "destination_filter"
CONF_STATION_QUERY = "station_query"

AUTOCOMPLETE_URL = (
    "https://webapp.rejseplanen.dk/bin/ajax-getstop.exe/mn"
    "?getstop=1&REQ0JourneyStopsS0A=255&REQ0JourneyStopsS0G={query}&js=true"
)
STBOARD_URL = (
    "https://webapp.rejseplanen.dk/bin/stboard.exe/mn"
    "?L=vs_rp4&input={station_id}&boardType=dep"
    "&productsFilter=1111111111111111"
    "&time=now&selectDate=today&maxJourneys=20&start=yes"
)

_DANISH_CHARS = str.maketrans(
    {"å": "aa", "Å": "Aa", "ø": "oe", "Ø": "Oe", "æ": "ae", "Æ": "Ae"}
)
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HomeAssistant/rejseplanen_a)"}


def _normalize_query(query: str) -> str:
    """Å→Aa, Ø→Oe, Æ→Ae så Rejseplanens API finder stationen korrekt."""
    return query.translate(_DANISH_CHARS)


def _fetch_stations(query: str) -> list[dict]:
    """Søg stationer via Rejseplanens autocomplete (synkront)."""
    url = AUTOCOMPLETE_URL.format(query=requests.utils.quote(_normalize_query(query)))
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        resp.encoding = "latin-1"
        m = re.search(r"SLs\.sls\s*=\s*(\{.*?\})\s*;", resp.text.strip(), re.DOTALL)
        if not m:
            return []
        data = json.loads(m.group(1))
        return [
            {"value": s["value"], "id": s["id"].lstrip("0") if "@" not in s.get("id", "") else s.get("extId", "").lstrip("0")}
            for s in data.get("suggestions", [])
            if "Sta" in s.get("typeStr", "") and s.get("extId", "").lstrip("0")
        ]
    except Exception as exc:  # noqa: BLE001
        _LOGGER.error("Fejl ved autocomplete-opslag: %s", exc)
        return []


def _fetch_available(station_id: str) -> tuple[list[str], list[str]]:
    """Hent stboard og returner (linjer, destinationer) som sorterede lister.

    Bruges til validering af linje- og destinationsfiltre.
    Returnerer ([], []) ved fejl — validering springes da over.
    """
    url = STBOARD_URL.format(station_id=station_id)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        resp.encoding = "latin-1"  # Stboardet returnerer latin-1, ikke UTF-8
        soup = BeautifulSoup(resp.text, "lxml")
        lines, dests = set(), set()
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) < 5:
                continue
            line = cells[2].get_text(strip=True).upper()
            dest = cells[4].get_text(strip=True)
            if line:
                lines.add(line)
            if dest:
                dests.add(dest)
        _LOGGER.debug("Station %s: fandt linjer=%s", station_id, sorted(lines))
        return sorted(lines), sorted(dests)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Kunne ikke hente stboard til validering (station %s): %s", station_id, exc)
        return [], []


def _validate_filters(
    line: str,
    dest: str,
    avail_lines: list[str],
    avail_dests: list[str],
) -> dict[str, str]:
    """Valider linje og destination mod kendte afgange. Returnerer errors-dict.

    Linje: exact match (bruger må skrive præcis det linjenavn der vises).
    Destination: substring match, case-insensitivt (delnavn er nok).
    Springer over hvis ingen afgange blev hentet (f.eks. nat/fejl).
    """
    errors: dict[str, str] = {}
    if not avail_lines and not avail_dests:
        return errors  # Ingen data — spring validering over
    if line and line.upper() not in avail_lines:
        errors[CONF_LINE_FILTER] = "line_not_found"
    if dest and not any(dest.lower() in d.lower() for d in avail_dests):
        errors[CONF_DESTINATION_FILTER] = "destination_not_found"
    return errors


# ── Config flow ───────────────────────────────────────────────────────────────

class RejseplanenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """To-trins opsætning: søg station → vælg station + filtre."""

    VERSION = 1

    def __init__(self):
        self._stations: list[dict] = []

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            query = user_input.get(CONF_STATION_QUERY, "").strip()
            if not query:
                errors[CONF_STATION_QUERY] = "query_empty"
            else:
                self._stations = await self.hass.async_add_executor_job(
                    _fetch_stations, query
                )
                if not self._stations:
                    errors[CONF_STATION_QUERY] = "no_stations_found"
                else:
                    return await self.async_step_station()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STATION_QUERY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_station(self, user_input=None):
        errors: dict[str, str] = {}
        placeholders = {"available_lines": "–", "available_destinations": "–"}

        if user_input is not None:
            station_id = user_input[CONF_STATION_ID]
            station_name = next(
                (s["value"] for s in self._stations if s["id"] == station_id),
                station_id,
            )
            line = user_input.get(CONF_LINE_FILTER, "").strip()
            dest = user_input.get(CONF_DESTINATION_FILTER, "").strip()

            if line or dest:
                avail_lines, avail_dests = await self.hass.async_add_executor_job(
                    _fetch_available, station_id
                )
                errors = _validate_filters(line, dest, avail_lines, avail_dests)
                if errors:
                    placeholders = {
                        "available_lines": ", ".join(avail_lines) or "–",
                        "available_destinations": ", ".join(avail_dests) or "–",
                    }

            if not errors:
                await self.async_set_unique_id(f"{DOMAIN}_{station_id}")
                self._abort_if_unique_id_configured()

                title = station_name
                if line:
                    title += f" – Linje {line.upper()}"
                if dest:
                    title += f" → {dest}"

                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_STATION_ID: station_id,
                        CONF_STATION_NAME: station_name,
                        CONF_LINE_FILTER: line,
                        CONF_DESTINATION_FILTER: dest,
                        CONF_SCAN_INTERVAL: int(
                            user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                        ),
                    },
                )

        return self.async_show_form(
            step_id="station",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STATION_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": s["id"], "label": s["value"]}
                                for s in self._stations
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_LINE_FILTER, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Optional(CONF_DESTINATION_FILTER, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=30, max=3600, step=10, mode=NumberSelectorMode.BOX
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return RejseplanenOptionsFlow(config_entry)


# ── Options flow ──────────────────────────────────────────────────────────────

class RejseplanenOptionsFlow(config_entries.OptionsFlow):
    """Rediger linje, destination og interval — ikke stationen."""

    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        errors: dict[str, str] = {}
        merged = {**self._config_entry.data, **self._config_entry.options}
        station_id = merged.get(CONF_STATION_ID, "")
        placeholders = {"available_lines": "–", "available_destinations": "–"}

        if user_input is not None:
            line = user_input.get(CONF_LINE_FILTER, "").strip()
            dest = user_input.get(CONF_DESTINATION_FILTER, "").strip()

            if line or dest:
                avail_lines, avail_dests = await self.hass.async_add_executor_job(
                    _fetch_available, station_id
                )
                errors = _validate_filters(line, dest, avail_lines, avail_dests)
                if errors:
                    placeholders = {
                        "available_lines": ", ".join(avail_lines) or "–",
                        "available_destinations": ", ".join(avail_dests) or "–",
                    }

            if not errors:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_LINE_FILTER: line,
                        CONF_DESTINATION_FILTER: dest,
                        CONF_SCAN_INTERVAL: int(
                            user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                        ),
                    },
                )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_LINE_FILTER, default=merged.get(CONF_LINE_FILTER, "")
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Optional(
                        CONF_DESTINATION_FILTER,
                        default=merged.get(CONF_DESTINATION_FILTER, ""),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=int(merged.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=30, max=3600, step=10, mode=NumberSelectorMode.BOX
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )
