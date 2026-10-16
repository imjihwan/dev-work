"""Synthetic account fixtures. No real home identifiers or tokens."""

import sys
from copy import deepcopy
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.commax_cloud.api import CommaxApi

ROOT = {
    "rootUuid": "test-root",
    "rootDevice": "switch",
    "commaxDevice": "light",
    "nickname": "Bedroom",
    "subDevice": [
        {
            "subUuid": "test-sub",
            "type": "readWrite",
            "sort": "switchBinary",
            "value": "off",
            "option1": "-1",
        }
    ],
}


class Service:
    def __init__(self):
        self.requests = []
        self.login_count = 0
        self.refresh_count = 0
        self.command_count = 0
        self.refresh_status = 200
        self.login_status = 200
        self.command_status = 200
        self.account = "test-user"
        self.access = "initial"
        self.version = 0
        self.clock = [1700000000.0]
        self.root = deepcopy(ROOT)
        self.url = ""
        self.rotate = True

    def tokens(self):
        self.version += 1
        self.access = f"fake-access-{self.version}"
        return {
            "access_token": self.access,
            "refresh_token": f"fake-refresh-{self.version}",
            "token_type": "Bearer",
            "expire_in": 259200,
            "user": {"userNo": self.account},
            "server": {"iot": {"ssl": "N", "ip": "127.0.0.1", "port": self.port}},
        }

    async def handle(self, request):
        self.requests.append(
            (request.method, request.path, dict(request.query), dict(request.headers))
        )
        if request.path == "/oauth/authorize":
            self.login_count += 1
            if self.login_status != 200:
                return web.json_response({"error": "invalid_credentials"}, status=self.login_status)
            return web.json_response(self.tokens())
        if request.path == "/oauth/token":
            self.refresh_count += 1
            if self.refresh_status != 200:
                return web.json_response({"error": "invalid_grant"}, status=self.refresh_status)
            response = self.tokens()
            if not self.rotate:
                response.pop("refresh_token")
            return web.json_response(response)
        if request.headers.get("Authorization") != f"Bearer {self.access}":
            return web.json_response({}, status=401)
        if request.path == "/v1/gateways":
            return web.json_response(
                {"gateways": {"gateway": [{"gatewayNo": "test-gateway", "model": "CDP-1000Y"}]}}
            )
        if request.path == "/v1/gateways/test-gateway":
            return web.json_response({"gateway": {"devices": {"object": [self.root]}}})
        if request.path == "/v1/command":
            self.command_count += 1
            self.last_payload = await request.json()
            if self.command_status != 200:
                return web.json_response({}, status=self.command_status)
            self.root["subDevice"][0]["value"] = self.last_payload["commands"]["cgpCommand"][0][
                "cgp"
            ]["object"]["subDevice"][0]["value"]
            return web.json_response({"commands": {"cgpCommand": ["test-command-id"]}})
        return web.json_response({}, status=404)

    def client(self, session, tokens=None, on_tokens=None):
        return CommaxApi(
            session,
            "test-id",
            "test-password",
            "test-device-uuid",
            tokens=tokens,
            on_tokens=on_tokens,
            auth_server=self.url,
            clock=lambda: self.clock[0],
        )


@pytest.fixture
async def service():
    instance = Service()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", instance.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    instance.port = site._server.sockets[0].getsockname()[1]
    instance.url = f"http://127.0.0.1:{instance.port}"
    yield instance
    await runner.cleanup()
