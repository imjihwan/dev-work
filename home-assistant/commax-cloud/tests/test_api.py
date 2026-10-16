"""Protocol and automatic credential recovery against a local HTTP server."""

import asyncio
from copy import deepcopy
from urllib.parse import quote

import aiohttp
import pytest

from custom_components.commax_cloud.api import (
    CommaxApi,
    CommaxApiError,
    CommaxAuthError,
    CommaxConnectionError,
    parse_lights,
)


async def test_real_http_login_double_encoding_headers_and_persistence(service):
    saved = []
    password = "pass+word&% /한글"
    async with aiohttp.ClientSession() as session:
        client = CommaxApi(
            session,
            "id+test",
            password,
            "unique-device",
            auth_server=service.url,
            on_tokens=saved.append,
            clock=lambda: service.clock[0],
        )
        await client.async_login()
        request = service.requests[0]
        assert request[2]["username"] == "id+test"
        assert request[2]["password"] == quote(password, safe="_-!.~'()*")
        assert request[3]["cmx-dvc-uuid"] == "unique-device"
        assert saved[-1]["expires_at"] == service.clock[0] + 259200
        assert password not in str(saved)


async def test_near_expiry_refresh_rotates_and_persists_tokens(service):
    saved = []
    async with aiohttp.ClientSession() as session:
        client = service.client(session, on_tokens=saved.append)
        await client.async_login()
        service.clock[0] += 259200 - 599
        await client.async_ensure_token()
        assert service.login_count == 1
        assert service.refresh_count == 1
        assert saved[-1]["refresh_token"] == "fake-refresh-2"
        assert saved[-1]["expires_at"] == service.clock[0] + 259200


async def test_rejected_refresh_token_automatically_logs_in_once(service):
    async with aiohttp.ClientSession() as session:
        client = service.client(session)
        await client.async_login()
        service.refresh_status = 400
        service.clock[0] += 259200
        await asyncio.gather(*(client.async_ensure_token() for _ in range(8)))
        assert service.refresh_count == 1
        assert service.login_count == 2
        assert len(await client.async_lights()) == 1


async def test_failed_auto_login_requires_reauth_without_repeated_password_attempts(service):
    async with aiohttp.ClientSession() as session:
        client = service.client(session)
        await client.async_login()
        service.refresh_status = 401
        service.login_status = 401
        service.clock[0] += 259200
        for _ in range(3):
            with pytest.raises(CommaxAuthError):
                await client.async_ensure_token()
        assert service.refresh_count == 1
        assert service.login_count == 2


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_transient_refresh_error_never_falls_back_to_password(service, status):
    async with aiohttp.ClientSession() as session:
        client = service.client(session)
        await client.async_login()
        service.refresh_status = status
        service.clock[0] += 259200
        with pytest.raises(CommaxConnectionError):
            await client.async_ensure_token()
        assert service.login_count == 1


async def test_simultaneous_expired_reads_do_not_duplicate_refresh(service):
    async with aiohttp.ClientSession() as session:
        client = service.client(session)
        await client.async_login()
        service.clock[0] += 259200
        result = await asyncio.gather(*(client.async_lights() for _ in range(6)))
        assert all(len(lights) == 1 for lights in result)
        assert service.refresh_count == 1


async def test_server_401_refreshes_then_retries_authenticated_read(service):
    async with aiohttp.ClientSession() as session:
        client = service.client(session)
        await client.async_login()
        service.access = "server-revoked-old-access"
        assert len(await client.async_lights()) == 1
        assert service.refresh_count == 1


async def test_restart_uses_persisted_tokens_without_new_login(service):
    async with aiohttp.ClientSession() as session:
        initial = service.client(session)
        await initial.async_login()
        restored = service.client(session, tokens=initial.token_data)
        await restored.async_lights()
        assert service.login_count == 1
        assert service.refresh_count == 0


async def test_refresh_preserves_refresh_token_when_not_rotated(service):
    async with aiohttp.ClientSession() as session:
        client = service.client(session)
        await client.async_login()
        old = client.token_data["refresh_token"]
        service.rotate = False
        service.clock[0] += 259200
        await client.async_ensure_token()
        assert client.token_data["refresh_token"] == old


async def test_account_identity_cannot_change_during_renewal(service):
    async with aiohttp.ClientSession() as session:
        client = service.client(session)
        await client.async_login()
        old = client.token_data
        service.account = "different-account"
        service.clock[0] += 259200
        with pytest.raises(CommaxAuthError):
            await client.async_ensure_token()
        assert client.token_data == old


async def test_on_off_body_and_confirmed_state(service):
    async with aiohttp.ClientSession() as session:
        client = service.client(session)
        lights = await client.async_lights()
        channel = next(iter(lights.values()))
        assert channel.state is False
        await client.async_set_light(channel, True)
        actual = await client.async_lights()
        assert actual[channel.unique_id].state is True
        payload = service.last_payload["commands"]["cgpCommand"][0]
        assert payload["gatewayNo"] == "test-gateway"
        assert payload["cgp"]["command"] == "set"
        assert payload["cgp"]["object"]["subDevice"] == [
            {
                "subUuid": "test-sub",
                "type": "readWrite",
                "sort": "switchBinary",
                "funcCommand": "set",
                "value": "on",
            }
        ]
        await client.async_set_light(actual[channel.unique_id], False)
        assert next(iter((await client.async_lights()).values())).state is False


async def test_failed_command_is_never_replayed(service):
    async with aiohttp.ClientSession() as session:
        client = service.client(session)
        channel = next(iter((await client.async_lights()).values()))
        service.command_status = 503
        with pytest.raises(CommaxConnectionError):
            await client.async_set_light(channel, True)
        assert service.command_count == 1


async def test_only_writable_light_channels_become_entities(service):
    response = {
        "gateway": {
            "devices": {
                "object": [
                    service.root,
                    {
                        **deepcopy(service.root),
                        "rootUuid": "outlet",
                        "commaxDevice": "standbyPowerSwitch",
                    },
                    {**deepcopy(service.root), "rootUuid": "gas", "commaxDevice": "gasLock"},
                    {**deepcopy(service.root), "rootUuid": "dim", "rootDevice": "dimmer"},
                ]
            }
        }
    }
    lights = parse_lights({"gatewayNo": "g"}, response)
    assert len(lights) == 1
    assert "initial" not in repr(next(iter(lights.values())))
    with pytest.raises(CommaxApiError):
        parse_lights({"gatewayNo": "g"}, {"unexpected": []})
