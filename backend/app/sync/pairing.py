"""配对 Token（V1.1 12.2）。

规则：一次性、5 分钟过期、绑定设备指纹。
一次性是最关键的一条 —— 长期凭证一旦泄露就是长期的洞。
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

TOKEN_TTL = timedelta(minutes=5)

REASON_OK = "OK"
REASON_UNKNOWN = "TOKEN_UNKNOWN"
REASON_EXPIRED = "TOKEN_EXPIRED"
REASON_USED = "TOKEN_USED"
REASON_FINGERPRINT = "FINGERPRINT_MISMATCH"


def _now() -> datetime:
    return datetime.now(UTC)


def fingerprint(seed: str) -> str:
    """由任意稳定标识算出的设备指纹（一期没有真实指纹时由前端提供种子）。"""

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


@dataclass(slots=True)
class _Token:
    value: str
    device_fingerprint: str
    expires_at: datetime
    used: bool = False


class PairingService:
    def __init__(self, *, ttl: timedelta = TOKEN_TTL) -> None:
        self._lock = threading.RLock()
        self._tokens: dict[str, _Token] = {}
        self._ttl = ttl

    def issue(self, device_fingerprint: str) -> tuple[str, str]:
        """签发一次性 Token。返回 (token, 过期时间)。"""

        token = secrets.token_urlsafe(24)
        expires = _now() + self._ttl
        with self._lock:
            self._tokens[token] = _Token(
                value=token, device_fingerprint=device_fingerprint, expires_at=expires
            )
        return token, expires.isoformat(timespec="seconds")

    def redeem(self, token: str, device_fingerprint: str) -> str:
        """校验并消费 Token，返回原因码（`OK` 表示通过）。"""

        with self._lock:
            entry = self._tokens.get(token)
            if entry is None:
                return REASON_UNKNOWN
            if entry.used:
                return REASON_USED
            if _now() > entry.expires_at:
                return REASON_EXPIRED
            if entry.device_fingerprint != device_fingerprint:
                # 绑定设备指纹：Token 被转发到别的设备就失效
                return REASON_FINGERPRINT
            entry.used = True
            return REASON_OK

    def pending(self) -> int:
        with self._lock:
            now = _now()
            return sum(
                1
                for item in self._tokens.values()
                if not item.used and item.expires_at > now
            )
