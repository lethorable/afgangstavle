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
    "&time=now&selectDate=today&maxJourneys=100&start=yes"
)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HomeAssistant/rejseplanen_a)"}
_DANISH_CHARS = str.maketrans(
    {"å": "aa", "Å": "Aa", "ø": "oe", "Ø": "Oe", "æ": "ae", "Æ": "Ae"}
)

_ALL_LINES_LABEL = "(Alle linjer)"
_ALL_DESTS_LABEL = "(Alle destinationer)"

# Reelle linjenavne: A-H, BUS 10, METRO M3, RE 1285, IC 866, ICL 66 osv.
# Skrammel fra parseren: stationsnavne med parenteser, kommaer, lange strenge
_LINE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\s]{0,12}$")


# ── Hjælpefunktioner ──────────────────────────────────────────────────────────


def _normalize_query(query: str) -> str:
    return query.translate(_DANISH_CHARS)


def _autocomplete(query: str) -> list[dict]:
    """Kør ét autocomplete-opslag, returner rå suggestions."""
    url = AUTOCOMPLETE_URL.format(query=requests.utils.quote(_normalize_query(query)))
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        resp.encoding = "latin-1"
        m = re.search(r"SLs\.sls\s*=\s*(\{.*?\})\s*;", resp.text.strip(), re.DOTALL)
        if not m:
            return []
        return json.loads(m.group(1)).get("suggestions", [])
    except Exception as exc:  # noqa: BLE001
        _LOGGER.error("Fejl ved autocomplete-opslag: %s", exc)
        return []


def _fetch_stations(query: str) -> list[dict]:
    """Søg stationer via flere autocomplete-opslag for at fange varianter.

    Rejseplanens API returnerer ofte kun ét exact-match resultat.
    'Ryparken' og 'Ryparken St.' er f.eks. to forskellige stationer.
    Vi søger med original query + ' St' for at finde begge.
    """
    queries = [query]
    if not query.lower().endswith((" st", " st.", " station")):
        queries.append(f"{query} St")

    seen_ids: set[str] = set()
    results: list[dict] = []

    for q in queries:
        for s in _autocomplete(q):
            ext_id = s.get("extId", "").lstrip("0")
            if not ext_id or ext_id in seen_ids:
                continue
            if "Sta" not in s.get("typeStr", ""):
                continue
            seen_ids.add(ext_id)
            results.append({"value": s["value"], "id": ext_id})

    return results


def _fetch_departures_raw(station_id: str) -> list[dict]:
    """Hent stboard og returner liste af {line, dest} dicts til dropdown-opbygning."""
    url = STBOARD_URL.format(station_id=station_id)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        resp.encoding = "latin-1"
        soup = BeautifulSoup(resp.text, "lxml")
        deps = []
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) < 5:
                continue
            line = cells[2].get_text(strip=True).upper().strip()
            # Filtrer skrammel: stationsnavne, tidspunkter osv. der ender i linje-kolonnen
            if not line or not _LINE_PATTERN.match(line):
                continue
            # Destinationsnavnet er i <span class="bold"> inde i cellen
            bold = cells[4].find("span", class_="bold")
            dest = bold.get_text(strip=True) if bold else cells[4].get_text(strip=True).split("-")[0].strip()
            if not dest:
                continue
            deps.append({"line": line, "dest": dest})
        _LOGGER.debug("Station %s: fandt %d afgange", station_id, len(deps))
        return deps
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Kunne ikke hente stboard (station %s): %s", station_id, exc)
        return []


def _line_options(departures: list[dict]) -> list[dict]:
    """Byg dropdown-options for linjevælger."""
    lines = sorted(set(d["line"] for d in departures))
    return [{"value": "", "label": _ALL_LINES_LABEL}] + [
        {"value": l, "label": l} for l in lines
    ]


def _dest_options(departures: list[dict], line_filter: str) -> list[dict]:
    """Byg dropdown-options for destinationsvælger, filtreret efter linje."""
    if line_filter:
        dests = sorted(set(d["dest"] for d in departures if d["line"] == line_filter))
    else:
        dests = sorted(set(d["dest"] for d in departures))
    return [{"value": "", "label": _ALL_DESTS_LABEL}] + [
        {"value": d, "label": d} for d in dests
    ]


# ── Config flow (4 trin) ─────────────────────────────────────────────────────


class RejseplanenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Søg station → vælg station → vælg linje → vælg destination."""

    VERSION = 1

    def __init__(self):
        self._stations: list[dict] = []
        self._station_id: str = ""
        self._station_name: str = ""
        self._departures: list[dict] = []
        self._line_filter: str = ""

    # ── Trin 1: Søg station ──────────────────────────────────────────────

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

    # ── Trin 2: Vælg station ─────────────────────────────────────────────

    async def async_step_station(self, user_input=None):
        if user_input is not None:
            self._station_id = user_input[CONF_STATION_ID]
            self._station_name = next(
                (s["value"] for s in self._stations if s["id"] == self._station_id),
                self._station_id,
            )
            await self.async_set_unique_id(f"{DOMAIN}_{self._station_id}")
            self._abort_if_unique_id_configured()

            self._departures = await self.hass.async_add_executor_job(
                _fetch_departures_raw, self._station_id
            )
            return await self.async_step_line()

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
                }
            ),
        )

    # ── Trin 3: Vælg linje ───────────────────────────────────────────────

    async def async_step_line(self, user_input=None):
        if user_input is not None:
            self._line_filter = user_input.get(CONF_LINE_FILTER, "")
            return await self.async_step_destination()

        return self.async_show_form(
            step_id="line",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LINE_FILTER, default=""): SelectSelector(
                        SelectSelectorConfig(
                            options=_line_options(self._departures),
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    # ── Trin 4: Vælg destination + interval ──────────────────────────────

    async def async_step_destination(self, user_input=None):
        if user_input is not None:
            dest = user_input.get(CONF_DESTINATION_FILTER, "")
            scan_interval = int(
                user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            )

            title = self._station_name
            if self._line_filter:
                title += f" – {self._line_filter}"
            if dest:
                title += f" → {dest}"

            return self.async_create_entry(
                title=title,
                data={
                    CONF_STATION_ID: self._station_id,
                    CONF_STATION_NAME: self._station_name,
                    CONF_LINE_FILTER: self._line_filter,
                    CONF_DESTINATION_FILTER: dest,
                    CONF_SCAN_INTERVAL: scan_interval,
                },
            )

        return self.async_show_form(
            step_id="destination",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DESTINATION_FILTER, default=""): SelectSelector(
                        SelectSelectorConfig(
                            options=_dest_options(
                                self._departures, self._line_filter
                            ),
                            mode=SelectSelectorMode.DROPDOWN,
                        )
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
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return RejseplanenOptionsFlow(config_entry)


# ── Options flow (2 trin) ─────────────────────────────────────────────────────


class RejseplanenOptionsFlow(config_entries.OptionsFlow):
    """Rediger linje → destination → interval. Station er låst."""

    def __init__(self, config_entry):
        self._config_entry = config_entry
        self._departures: list[dict] = []
        self._line_filter: str = ""

    # ── Trin 1: Vælg linje ───────────────────────────────────────────────

    async def async_step_init(self, user_input=None):
        merged = {**self._config_entry.data, **self._config_entry.options}
        station_id = merged.get(CONF_STATION_ID, "")

        if user_input is not None:
            self._line_filter = user_input.get(CONF_LINE_FILTER, "")
            return await self.async_step_options_dest()

        self._departures = await self.hass.async_add_executor_job(
            _fetch_departures_raw, station_id
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LINE_FILTER, default=merged.get(CONF_LINE_FILTER, "")
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=_line_options(self._departures),
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    # ── Trin 2: Vælg destination + interval ──────────────────────────────

    async def async_step_options_dest(self, user_input=None):
        merged = {**self._config_entry.data, **self._config_entry.options}

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_LINE_FILTER: self._line_filter,
                    CONF_DESTINATION_FILTER: user_input.get(
                        CONF_DESTINATION_FILTER, ""
                    ),
                    CONF_SCAN_INTERVAL: int(
                        user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                    ),
                },
            )

        return self.async_show_form(
            step_id="options_dest",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DESTINATION_FILTER,
                        default=merged.get(CONF_DESTINATION_FILTER, ""),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=_dest_options(
                                self._departures, self._line_filter
                            ),
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=int(
                            merged.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=30, max=3600, step=10, mode=NumberSelectorMode.BOX
                        )
                    ),
                }
            ),
        )
