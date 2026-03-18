"""Config flow for Rejseplanen Linje A."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

DOMAIN = "rejseplanen_a"
DEFAULT_SCAN_INTERVAL = 60


def _scan_interval_schema(default: int) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_SCAN_INTERVAL, default=default): NumberSelector(
                NumberSelectorConfig(
                    min=30,
                    max=3600,
                    step=10,
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
    )


class RejseplanenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Opsætningsguide til Rejseplanen Linje A."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="Linje A – Åmarken → Hillerød",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_scan_interval_schema(DEFAULT_SCAN_INTERVAL),
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return RejseplanenOptionsFlow(config_entry)


class RejseplanenOptionsFlow(config_entries.OptionsFlow):
    """Ændring af indstillinger efter installation."""

    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = int(
            self._config_entry.options.get(
                CONF_SCAN_INTERVAL,
                self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )
        )

        return self.async_show_form(
            step_id="init",
            data_schema=_scan_interval_schema(current),
        )
