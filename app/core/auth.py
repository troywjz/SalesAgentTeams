from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings


AUTH_SCHEME = HTTPBearer(auto_error=False)


def issue_auth_token(
    *,
    subject: str,
    scope: str,
    display_name: str = "",
    ttl_seconds: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    now = int(time.time())
    ttl = int(ttl_seconds or settings.auth_token_ttl_seconds)
    payload = {
        "sub": subject,
        "scope": scope,
        "name": display_name,
        "iat": now,
        "exp": now + max(60, ttl),
    }
    token = _encode_token(payload, settings.app_secret_key)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": payload["exp"],
    }


def verify_auth_token(
    token: str,
    *,
    required_scope: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    try:
        payload_part, signature = token.split(".", 1)
    except ValueError as exc:
        raise _auth_error("登录已失效，请重新登录。") from exc
    expected = _signature(payload_part, settings.app_secret_key)
    if not hmac.compare_digest(signature, expected):
        raise _auth_error("登录已失效，请重新登录。")
    try:
        payload = json.loads(_b64decode(payload_part).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _auth_error("登录已失效，请重新登录。") from exc
    if str(payload.get("scope") or "") != required_scope:
        raise _auth_error("没有访问权限。", status.HTTP_403_FORBIDDEN)
    if int(payload.get("exp") or 0) < int(time.time()):
        raise _auth_error("登录已过期，请重新登录。")
    return payload


def require_admin_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(AUTH_SCHEME),
) -> dict[str, Any]:
    return _require_scope(credentials, "admin")


def require_sales_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(AUTH_SCHEME),
) -> dict[str, Any]:
    return _require_scope(credentials, "sales")


def verify_admin_password(
    username: str,
    password: str,
    *,
    settings: Settings | None = None,
) -> bool:
    settings = settings or get_settings()
    if not hmac.compare_digest(username.strip(), settings.admin_username.strip()):
        return False
    if settings.admin_password_hash.strip():
        return hmac.compare_digest(_sha256(password), settings.admin_password_hash.strip())
    return hmac.compare_digest(password, settings.admin_password)


def _require_scope(
    credentials: HTTPAuthorizationCredentials | None,
    scope: str,
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _auth_error("请先登录。")
    return verify_auth_token(credentials.credentials, required_scope=scope)


def _encode_token(payload: dict[str, Any], secret: str) -> str:
    payload_part = _b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return f"{payload_part}.{_signature(payload_part, secret)}"


def _signature(payload_part: str, secret: str) -> str:
    key = (secret or "change-me").encode("utf-8")
    digest = hmac.new(key, payload_part.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _auth_error(
    detail: str,
    status_code: int = status.HTTP_401_UNAUTHORIZED,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
