import asyncio
import logging

import aiohttp

from homeassistant.core import HomeAssistant

from .const import DEFAULT_TIMEOUT

_LOGGER = logging.getLogger(__name__)


def _unwrap(body: dict) -> dict:
    """Extract the inner `data` field from a MagicPush API response wrapper.

    MagicPush wraps all responses in: { success, code, message, data, timestamp }
    """
    return body.get("data", body)


class MagicPushHub:
    """Manages HTTP communication with the MagicPush server."""

    def __init__(self, hass: HomeAssistant, url: str, username: str, password: str) -> None:
        self.hass = hass
        self._url = url.rstrip("/")
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._endpoints: dict[str, dict] = {}
        self._session: aiohttp.ClientSession | None = None

    @property
    def url(self) -> str:
        return self._url

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _request_json(self, method: str, path: str, **kwargs) -> dict:
        session = await self._ensure_session()
        headers = dict(kwargs.pop("headers", {}))
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        try:
            async with asyncio.timeout(DEFAULT_TIMEOUT):
                resp = await session.request(
                    method, f"{self._url}{path}", headers=headers, **kwargs
                )
                if resp.status == 401 and self._refresh_token:
                    await self._refresh()
                    headers["Authorization"] = f"Bearer {self._access_token}"
                    resp = await session.request(
                        method, f"{self._url}{path}", headers=headers, **kwargs
                    )
                body = await resp.json()
                if resp.status != 200:
                    msg = body.get("message", str(resp.status))
                    if "邮箱或密码错误" in msg or "无效" in msg:
                        raise InvalidAuthError(msg)
                    raise CannotConnectError(msg)
                return body
        except asyncio.TimeoutError as e:
            raise CannotConnectError("Request to MagicPush timed out") from e

    async def login(self) -> dict:
        body = await self._request_json(
            "POST",
            "/api/auth/login",
            json={"email": self._username, "password": self._password},
        )
        data = _unwrap(body)
        self._access_token = data["accessToken"]
        self._refresh_token = data["refreshToken"]
        return data

    async def _refresh(self) -> None:
        body = await self._request_json(
            "POST",
            "/api/auth/refresh",
            json={"refreshToken": self._refresh_token},
        )
        data = _unwrap(body)
        self._access_token = data["accessToken"]
        self._refresh_token = data["refreshToken"]

    async def test_connection(self) -> bool:
        try:
            await self.login()
            return True
        except Exception as e:
            _LOGGER.error("Connection test failed: %s", e)
            return False

    async def fetch_endpoints(self) -> dict[str, dict]:
        all_endpoints: list[dict] = []
        page = 1
        page_size = 100

        while True:
            body = await self._request_json(
                "GET", f"/api/endpoints?page={page}&pageSize={page_size}"
            )
            data = _unwrap(body)
            all_endpoints.extend(data.get("list", []))

            total_pages = data.get("pagination", {}).get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1

        self._endpoints = {}
        for ep in all_endpoints:
            name = ep.get("name", f"endpoint_{ep['id']}")
            self._endpoints[name] = ep
        _LOGGER.debug("Fetched %d endpoints from %s", len(self._endpoints), self._url)
        return self._endpoints

    @property
    def endpoints(self) -> dict[str, dict]:
        return self._endpoints

    async def send_push(
        self,
        endpoint_token: str,
        title: str = "",
        content: str = "",
        msg_type: str = "text",
        url: str = "",
    ) -> dict:
        session = await self._ensure_session()
        payload = {"title": title, "content": content, "type": msg_type}
        if url:
            payload["url"] = url
        try:
            async with asyncio.timeout(DEFAULT_TIMEOUT):
                resp = await session.post(
                    f"{self._url}/api/push",
                    headers={"Authorization": f"Bearer {endpoint_token}"},
                    json=payload,
                )
                body = await resp.json()
                return _unwrap(body)
        except asyncio.TimeoutError as e:
            raise CannotConnectError("Push request timed out") from e

    async def cleanup(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()


class InvalidAuthError(Exception):
    """Raised when authentication with MagicPush fails."""


class CannotConnectError(Exception):
    """Raised when connection to MagicPush fails."""
