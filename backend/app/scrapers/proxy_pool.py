from __future__ import annotations

import asyncio
from dataclasses import dataclass
from itertools import cycle
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProxyConfig:
    server: str
    username: str | None = None
    password: str | None = None

    @classmethod
    def from_url(cls, value: str) -> "ProxyConfig":
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https", "socks5"} or not parsed.hostname or not parsed.port:
            raise ValueError(f"Invalid proxy URL: {value}")
        server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        return cls(server=server, username=parsed.username, password=parsed.password)

    def playwright(self) -> dict[str, str]:
        result = {"server": self.server}
        if self.username:
            result["username"] = self.username
        if self.password:
            result["password"] = self.password
        return result

    def aiohttp_url(self) -> str:
        if not self.username:
            return self.server
        parsed = urlparse(self.server)
        return f"{parsed.scheme}://{self.username}:{self.password or ''}@{parsed.hostname}:{parsed.port}"


class ProxyPool:
    def __init__(self, values: list[str]) -> None:
        self.proxies = [ProxyConfig.from_url(value) for value in values if value.strip()]
        self._cycle = cycle(self.proxies) if self.proxies else None
        self._lock = asyncio.Lock()

    async def next(self) -> ProxyConfig | None:
        if not self._cycle:
            return None
        async with self._lock:
            return next(self._cycle)
