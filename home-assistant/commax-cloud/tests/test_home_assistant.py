"""Exercise HA's real config flow, entity services, reauthentication and unload."""

from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from homeassistant import loader
from homeassistant.config_entries import ConfigEntries, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry, entity_registry

from custom_components.commax_cloud.api import CommaxApi, CommaxAuthError
from custom_components.commax_cloud.const import CONF_SCAN_INTERVAL, CONF_TOKENS, DOMAIN


@pytest.fixture
async def hass(tmp_path):
    instance = HomeAssistant(str(tmp_path))
    loader.async_setup(instance)
    instance.config_entries = ConfigEntries(instance, {})
    await instance.config_entries.async_initialize()
    device_registry.async_setup(instance)
    await device_registry.async_load(instance)
    await entity_registry.async_load(instance)
    yield instance
    await instance.async_stop(force=True)


@pytest.fixture
async def local_api(service):
    def create(*args, **kwargs):
        kwargs.update(auth_server=service.url, clock=lambda: service.clock[0])
        return CommaxApi(*args, **kwargs)

    async with aiohttp.ClientSession() as session:
        with (
            patch("custom_components.commax_cloud.config_flow.CommaxApi", side_effect=create),
            patch("custom_components.commax_cloud.CommaxApi", side_effect=create),
            patch(
                "custom_components.commax_cloud.config_flow.async_get_clientsession",
                return_value=session,
            ),
            patch("custom_components.commax_cloud.async_get_clientsession", return_value=session),
        ):
            yield


async def setup_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
        data={CONF_USERNAME: "test-id", CONF_PASSWORD: "test-password"},
    )
    await hass.async_block_till_done()
    assert result["type"] == "create_entry", result
    entry = result["result"]
    assert entry.state == ConfigEntryState.LOADED
    return entry


async def test_ui_setup_light_services_rotation_and_unload(hass, service, local_api):
    entry = await setup_entry(hass)
    assert entry.data[CONF_USERNAME] == "test-id"
    assert entry.data[CONF_PASSWORD] == "test-password"
    states = hass.states.async_all("light")
    assert len(states) == 1
    assert states[0].state == "off"
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": states[0].entity_id}, blocking=True
    )
    assert hass.states.get(states[0].entity_id).state == "on"
    await hass.services.async_call(
        "light", "turn_off", {"entity_id": states[0].entity_id}, blocking=True
    )
    assert hass.states.get(states[0].entity_id).state == "off"
    coordinator = entry.runtime_data
    service.clock[0] += 259200
    await coordinator.client.async_ensure_token()
    await hass.async_block_till_done()
    assert entry.data[CONF_TOKENS]["access_token"] == "fake-access-2"
    assert entry.runtime_data is coordinator  # A token save must not reload the integration.
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert coordinator._closing


async def test_ui_rejects_bad_credentials(hass, service, local_api):
    service.login_status = 401
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={CONF_USERNAME: "bad", CONF_PASSWORD: "bad"}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_expired_refresh_auto_login_persists_new_tokens(hass, service, local_api):
    entry = await setup_entry(hass)
    service.refresh_status = 400
    service.clock[0] += 259200
    await entry.runtime_data.async_request_refresh()
    await hass.async_block_till_done()
    assert service.login_count == 2
    assert entry.data[CONF_TOKENS]["access_token"] == "fake-access-2"


async def test_reauth_flow_updates_password_and_keeps_entity_id(hass, service, local_api):
    entry = await setup_entry(hass)
    entity_id = hass.states.async_all("light")[0].entity_id
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reauth", "entry_id": entry.entry_id}, data=entry.data
    )
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "test-id", CONF_PASSWORD: "new-password"}
    )
    await hass.async_block_till_done()
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"
    assert hass.states.get(entity_id) is not None


async def test_options_flow_reload_changes_polling_interval(hass, service, local_api):
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60}
    )
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.runtime_data.update_interval.total_seconds() == 60


async def test_coordinator_raises_auth_error_for_rejected_password(hass, service, local_api):
    entry = await setup_entry(hass)
    with patch.object(
        entry.runtime_data.client, "async_lights", AsyncMock(side_effect=CommaxAuthError)
    ):
        with pytest.raises(ConfigEntryAuthFailed):
            await entry.runtime_data._async_update_data()


async def test_background_token_maintenance_and_cleanup(hass, service, local_api):
    actions = []
    stopped = []

    def track(hass, action, interval):
        assert interval.total_seconds() == 60
        actions.append(action)
        return lambda: stopped.append(True)

    with patch(
        "custom_components.commax_cloud.coordinator.async_track_time_interval", side_effect=track
    ):
        entry = await setup_entry(hass)
    service.clock[0] += 259200
    await actions[0](None)
    assert service.refresh_count == 1
    assert entry.data[CONF_TOKENS]["access_token"] == "fake-access-2"
    await hass.config_entries.async_unload(entry.entry_id)
    assert stopped
    service.clock[0] += 259200
    await actions[0](None)
    assert service.refresh_count == 1


async def test_unknown_light_state_is_unavailable_then_recovers(hass, service, local_api):
    entry = await setup_entry(hass)
    entity_id = hass.states.async_all("light")[0].entity_id
    service.root["subDevice"][0]["value"] = "unknown"
    await entry.runtime_data.async_refresh()
    assert hass.states.get(entity_id).state == "unavailable"
    service.root["subDevice"][0]["value"] = "on"
    await entry.runtime_data.async_refresh()
    assert hass.states.get(entity_id).state == "on"


async def test_reauth_rejects_different_account_without_replacing_saved_credentials(
    hass, service, local_api
):
    entry = await setup_entry(hass)
    original = dict(entry.data)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reauth", "entry_id": entry.entry_id}, data=entry.data
    )
    service.account = "another-user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "another-id", CONF_PASSWORD: "another-password"}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "wrong_account"
    assert dict(entry.data) == original
