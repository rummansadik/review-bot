from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time

import httpx
import jwt

_TOKEN_CACHE: dict[str, object] = {
    "token": None,
    "expires_at": None,
}


def normalize_private_key(private_key: str) -> str:
    if private_key is None:
        return ""
    key = private_key.strip()
    if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
        key = key[1:-1]
    return key.replace("\\n", "\n")


def _build_jwt(app_id: int, private_key: str) -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 9 * 60,
        "iss": app_id,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


def _parse_expires_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _token_is_valid(expires_at: datetime | None) -> bool:
    if not expires_at:
        return False
    return expires_at - timedelta(minutes=5) > datetime.now(timezone.utc)


def get_installation_token(
    *,
    app_id: int,
    installation_id: int,
    private_key: str,
    api_base: str,
    timeout: float = 10.0,
) -> str:
    cached_token = _TOKEN_CACHE.get("token")
    cached_expires_at = _TOKEN_CACHE.get("expires_at")

    if isinstance(cached_token, str) and isinstance(cached_expires_at, datetime):
        if _token_is_valid(cached_expires_at):
            return cached_token

    jwt_token = _build_jwt(app_id, private_key)
    url = f"{api_base}/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "review-bot",
    }

    response = httpx.post(url, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        raise RuntimeError(f"Failed to fetch installation token ({response.status_code})")

    payload = response.json()
    token = payload.get("token")
    expires_at = _parse_expires_at(payload.get("expires_at"))

    if not token:
        raise RuntimeError("GitHub installation token missing in response")

    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = expires_at
    return token
