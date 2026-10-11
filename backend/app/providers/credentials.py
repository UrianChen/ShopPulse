"""Authenticated encryption; plaintext exists only in process memory."""

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select, text

from app.core.config import settings
from app.core.errors import AppError
from app.db.models import ModelConfig


def cipher(version: int) -> AESGCM:
    config = settings()
    filename = (
        config.credential_master_key_file
        if version == config.credential_key_version
        else config.credential_old_keys.get(version)
    )
    if not filename:
        raise AppError(503, "CREDENTIAL_UNAVAILABLE", "凭证主密钥版本不可用。")
    try:
        key = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=b"shoppulse/credentials/v1"
        ).derive(config.secret(filename).encode())
        return AESGCM(key)
    except Exception:
        raise AppError(503, "CREDENTIAL_UNAVAILABLE", "无法读取凭证主密钥。") from None


def aad(item: ModelConfig, version: int) -> bytes:
    return f"shoppulse:{item.workspace_id}:{item.id}:{version}".encode()


def encrypt(item: ModelConfig, value: str) -> None:
    version = settings().credential_key_version
    nonce = os.urandom(12)
    encrypted = cipher(version).encrypt(nonce, value.encode(), aad(item, version))
    item.credential_ciphertext = base64.b64encode(nonce + encrypted).decode()
    item.credential_key_version = version


def decrypt(item: ModelConfig) -> str:
    if not item.credential_ciphertext:
        return ""
    try:
        raw = base64.b64decode(item.credential_ciphertext, validate=True)
        return (
            cipher(item.credential_key_version)
            .decrypt(raw[:12], raw[12:], aad(item, item.credential_key_version))
            .decode()
        )
    except Exception:
        raise AppError(503, "CREDENTIAL_UNAVAILABLE", "凭证无法解密，请检查主密钥版本。") from None


def lock_configs(db):
    # Shared with API writes; key rotation cannot race new writes or default selection.
    db.execute(text("SELECT pg_advisory_xact_lock(731603)"))


def rotate(db, dry_run=False) -> int:
    lock_configs(db)
    items = db.scalars(select(ModelConfig).with_for_update()).all()
    count = 0
    for item in items:
        if item.credential_ciphertext:
            value = decrypt(item)  # Verify even credentials already on the current version.
            if item.credential_key_version != settings().credential_key_version:
                count += 1
                if not dry_run:
                    encrypt(item, value)
                    if decrypt(item) != value:
                        raise AppError(503, "CREDENTIAL_UNAVAILABLE", "轮换验证失败。")
    return count
