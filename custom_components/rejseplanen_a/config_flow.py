"""Config flow for Rejseplanen Afgangstavle."""

from __future__ import annotations

import json
import logging
import re

import requests
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

_DANISH_CHARS = str.maketrans({"å": "aa", "Å": "Aa", "ø": "oe", "Ø": "Oe", "æ": "ae", "Æ": "Ae"})


def _normalize_query(query: str) -> str:
    """Oversæt danske bogstaver til ASCII så Rejseplanens API finder stationen korrekt.
    F.eks. 'Åmarken' → 'Aamarken', 'Nørreport' → 'Noerreport'.
    """
    return query.translate(_DANISH_CHARS)


def _fetch_stations(query: str) -> list[dict]:
    """Søg efter stationer via Rejseplanens autocomplete-endpoint (synkront)."""
    url = AUTOCOMPLETE_URL.format(query=requests.utils.quote(_normalize_query(query)))
    headers = {"User-Agent": "Mozilla/5.0 (compatible; HomeAssistant/rejseplanen_a)"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        # API'et returnerer latin-1 selvom det ligner UTF-8
        resp.encoding = "latin-1"
        text = resp.text.strip()
        # Svar-format: SLs.sls={...};SLs.showSuggestion();
        m = re.search(r"SLs\.sls\s*=\s*(\{.*?\})\s*;", text, re.DOTALL)
        if not m:
            _LOGGER.error("Uventet format fra autocomplete-API: %s", text[:200])
            return []
        data = json.loads(m.group(1))
        results = []
        for s in data.get("suggestions", []):
            ext_id = s.get("extId", "").lstrip("0")
            name = s.get("value", "")
            # typeStr "[Sta/Stp]" = station/stoppested
            if ext_id and "Sta" in s.get("typeStr", ""):
                results.append({"value": name, "id": ext_id})
        return results
    except Exception as exc:  # noqa: BLE001
        _LOGGER.error("Fejl ved autocomplete-opslag: %s", exc)
        return []


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
        errors = {}
        if user_input is not None:
            station_id = user_input[CONF_STATION_ID]
            station_name = next(
                (s["value"] for s in self._stations if s["id"] == station_id),
                station_id,
            )
            await self.async_set_unique_id(f"{DOMAIN}_{station_id}")
            self._abort_if_unique_id_configured()

            line = user_input.get(CONF_LINE_FILTER, "").strip()
            dest = user_input.get(CONF_DESTINATION_FILTER, "").strip()

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

        station_options = [
            {"value": s["id"], "label": s["value"]} for s in self._stations
        ]

        return self.async_show_form(
            step_id="station",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STATION_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=station_options,
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
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return RejseplanenOptionsFlow(config_entry)


class RejseplanenOptionsFlow(config_entries.OptionsFlow):
    """Rediger linje, destination og interval — ikke stationen."""

    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_LINE_FILTER: user_input.get(CONF_LINE_FILTER, "").strip(),
                    CONF_DESTINATION_FILTER: user_input.get(
                        CONF_DESTINATION_FILTER, ""
                    ).strip(),
                    CONF_SCAN_INTERVAL: int(
                        user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                    ),
                },
            )

        merged = {**self._config_entry.data, **self._config_entry.options}

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
