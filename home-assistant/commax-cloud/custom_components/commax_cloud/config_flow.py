"""UI setup, options and reauthentication for COMMAX Cloud."""

import uuid
from collections.abc import Mapping
from typing import Any

try:
    import probatio as vol
except ImportError:  # HA releases before the schema-library migration.
    import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import CommaxApi, CommaxAuthError, CommaxConnectionError, CommaxError
from .const import (
    CONF_DEVICE_UUID,
    CONF_SCAN_INTERVAL,
    CONF_TOKENS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    NAME,
)


class CommaxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._device_uuid = str(uuid.uuid4())

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CommaxOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        return await self._credentials_step("user", user_input)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]):
        self._device_uuid = entry_data[CONF_DEVICE_UUID]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        return await self._credentials_step("reauth_confirm", user_input)

    async def _credentials_step(self, step: str, user_input: dict[str, Any] | None):
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry() if step == "reauth_confirm" else None
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            client = CommaxApi(
                async_get_clientsession(self.hass),
                username,
                password,
                self._device_uuid,
            )
            try:
                await client.async_login()
                lights = await client.async_lights()
            except CommaxAuthError:
                errors["base"] = "invalid_auth"
            except CommaxConnectionError:
                errors["base"] = "cannot_connect"
            except CommaxError:
                errors["base"] = "invalid_response"
            else:
                if not lights:
                    errors["base"] = "no_lights"
                elif entry is not None and entry.unique_id != client.user_no:
                    errors["base"] = "wrong_account"
                else:
                    await self.async_set_unique_id(client.user_no)
                    data = {
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_DEVICE_UUID: self._device_uuid,
                        CONF_TOKENS: client.token_data,
                    }
                    if entry is not None:
                        data["auth_generation"] = entry.data.get("auth_generation", 0) + 1
                        self.hass.config_entries.async_update_entry(
                            entry, data={**entry.data, **data}
                        )
                        return self.async_abort(reason="reauth_successful")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title=NAME, data=data)
        default_username = entry.data[CONF_USERNAME] if entry else ""
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=default_username): TextSelector(),
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id=step, data_schema=schema, errors=errors)


class CommaxOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            interval = int(user_input[CONF_SCAN_INTERVAL])
            if 15 <= interval <= 300:
                return self.async_create_entry(title="", data={CONF_SCAN_INTERVAL: interval})
            errors = {"base": "invalid_interval"}
        else:
            errors = {}
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(min=15, max=300, step=1, mode=NumberSelectorMode.BOX)
                    )
                }
            ),
        )
