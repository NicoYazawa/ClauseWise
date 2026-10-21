"""AES-256-GCM encryption of sensitive fields (design doc 3.5.3): key derived from SECRET_KEY; never hardcode."""
import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_PREFIX = "enc:"


def _derive_key() -> bytes:
    return hashlib.sha256(settings.secret_key.encode("utf-8")).digest()


def encrypt_text(plain: str | None) -> str | None:
    if plain is None or plain == "":
        return plain
    if plain.startswith(_PREFIX):
        return plain  # already encrypted; idempotent
    nonce = os.urandom(12)
    aes = AESGCM(_derive_key())
    ct = aes.encrypt(nonce, plain.encode("utf-8"), None)
    return _PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt_text(token: str | None) -> str | None:
    if token is None or token == "":
        return token
    if not token.startswith(_PREFIX):
        return token  # tolerate legacy plaintext data
    raw = base64.b64decode(token[len(_PREFIX):])
    nonce, ct = raw[:12], raw[12:]
    aes = AESGCM(_derive_key())
    return aes.decrypt(nonce, ct, None).decode("utf-8")
