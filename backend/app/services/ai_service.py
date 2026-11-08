"""个人本地 AI 配置与 OpenAI 兼容流式客户端。"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from cryptography.fernet import Fernet, InvalidToken
from openai import OpenAI

from app.models.ai_setting import AISetting
from app.schemas.common import ok
from app.services.base import ServiceBase, service_call
from app.utils.runtime import get_logger

logger = get_logger("ai_service")
KEY_PATH = Path(__file__).resolve().parents[2] / "storage" / ".ai_setting.key"


class AIKeyUnreadableError(RuntimeError):
    """已保存的 API key 无法用当前密钥解密。"""


def mask_api_key(value: str) -> str | None:
    """短 key 整体遮蔽；长 key 保留前四位和后四位，中间固定遮蔽。"""
    if not value:
        return None
    if len(value) < 9:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def _load_key() -> bytes:
    """读取本地密钥；文件缺失时原子创建，避免并发请求互相覆盖密钥。"""
    try:
        return KEY_PATH.read_bytes().strip()
    except FileNotFoundError:
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        candidate = Fernet.generate_key()
        try:
            fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return KEY_PATH.read_bytes().strip()
        with os.fdopen(fd, "wb") as key_file:
            key_file.write(candidate)
        return candidate


def _fernet() -> Fernet:
    env_key = os.getenv("AI_SETTING_SECRET", "").strip()
    if env_key:
        raw = hashlib.sha256(env_key.encode("utf-8")).digest()
        return Fernet(__import__("base64").urlsafe_b64encode(raw))
    return Fernet(_load_key())


def encrypt_api_key(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii") if value else ""


def decrypt_api_key(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise AIKeyUnreadableError("API Key 加密信息已失效，请重新填写") from exc


def classify_ai_error(exc: Exception) -> tuple[str, str]:
    name = type(exc).__name__.lower()
    if "unreadable" in name:
        return "api_key_unreadable", "API Key 加密信息已失效，请重新填写"
    if "timeout" in name:
        return "timeout", "AI 服务请求超时"
    if "ratelimit" in name:
        return "rate_limited", "AI 服务请求过于频繁"
    if "authentication" in name:
        return "authentication_failed", "AI 服务认证失败"
    if "notfound" in name:
        return "model_not_found", "AI 服务或模型不存在"
    if "connection" in name:
        return "connection_failed", "无法连接 AI 服务"
    return "provider_error", "AI 服务暂时不可用"


def chunk_text(value: str, size: int = 48) -> Iterable[str]:
    for index in range(0, len(value), size):
        yield value[index:index + size]


def openai_stream(
    setting: AISetting,
    messages: list[dict[str, str]],
    max_tokens: int | None = None,
) -> Iterable[tuple[str, str]]:
    api_key = decrypt_api_key(setting.api_key_encrypted)
    if not api_key:
        raise RuntimeError("AI API key 未配置")
    client = OpenAI(
        api_key=api_key,
        base_url=setting.base_url.rstrip("/"),
        timeout=float(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "60")),
    )
    kwargs = {
        "model": setting.model,
        "messages": messages,
        "stream": True,
        "temperature": 0.15,
    }
    if max_tokens and max_tokens > 0:
        kwargs["max_tokens"] = max_tokens
    response = client.chat.completions.create(**kwargs)
    for chunk in response:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            yield "reasoning", str(reasoning)
        content = getattr(delta, "content", None)
        if content:
            yield "delta", str(content)


class AISettingService(ServiceBase):
    @service_call
    def get(self):
        setting = self.db.get(AISetting, 1)
        if setting is None:
            return ok(data={
                "configured": False,
                "enabled": False,
                "api_key_masked": None,
                "api_key_readable": True,
            })
        api_key_masked = None
        api_key_readable = True
        if setting.api_key_encrypted:
            try:
                api_key_masked = mask_api_key(decrypt_api_key(setting.api_key_encrypted))
            except AIKeyUnreadableError:
                api_key_readable = False
                api_key_masked = "****"
                logger.warning("AI API Key 无法解密：加密密钥可能已变更或本地密钥文件已丢失")
        return ok(data={
            "configured": bool(
                setting.base_url
                and setting.model
                and setting.api_key_encrypted
                and api_key_readable
            ),
            "provider": setting.provider,
            "base_url": setting.base_url,
            "model": setting.model,
            "enabled": bool(setting.enabled),
            "api_key_masked": api_key_masked,
            "api_key_readable": api_key_readable,
            "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
        })

    @service_call
    def update(self, payload: dict):
        now = datetime.now(timezone.utc)
        setting = self.db.get(AISetting, 1)
        if setting is None:
            setting = AISetting(
                id=1,
                provider=payload.get("provider") or "openai-compatible",
                base_url=payload["base_url"],
                model=payload["model"],
                api_key_encrypted="",
                enabled=bool(payload.get("enabled", True)),
                created_at=now,
                updated_at=now,
            )
            self.db.add(setting)
        setting.provider = payload.get("provider") or "openai-compatible"
        setting.base_url = payload["base_url"].strip()
        setting.model = payload["model"].strip()
        setting.enabled = bool(payload.get("enabled", True))
        if payload.get("api_key"):
            setting.api_key_encrypted = encrypt_api_key(str(payload["api_key"]).strip())
        setting.updated_at = now
        self.commit()
        return self.get()

    @service_call
    def test_connection(self):
        setting = self.db.get(AISetting, 1)
        if setting is None or not setting.enabled:
            return ok(data={"connected": False, "reason_code": "not_configured", "message": "尚未配置或未启用 AI 服务"})
        try:
            text = "".join(part for kind, part in openai_stream(
                setting,
                [{"role": "user", "content": "只回复 OK"}],
                max_tokens=16,
            ) if kind == "delta")
            if not text.strip():
                raise RuntimeError("empty response")
            return ok(data={"connected": True, "reason_code": "ok", "message": "连接成功"})
        except Exception as exc:  # noqa: BLE001
            code, message = classify_ai_error(exc)
            return ok(data={"connected": False, "reason_code": code, "message": message})
