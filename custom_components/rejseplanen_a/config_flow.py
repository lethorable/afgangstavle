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


class RejseplanenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Opsætningsguide til Rejseplanen Linje A."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        # Tillad kun én instans
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="Linje A – Åmarken → Hillerød",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=30,
                            max=3600,
                            step=10,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
