"""Encrypts a visitor's own Gemini key while it travels through the job queue.

The key is never written to storage or logs; it only exists encrypted inside queue
messages, which expire. The encryption key is derived from the RUN_SECRET env var.
"""

from __future__ import annotations

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken


class KeyVault:
    def __init__(self, secret: str):
        digest = hashlib.sha256(secret.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    @classmethod
    def ephemeral(cls) -> "KeyVault":
        """A per-process vault for local development."""
        return cls(secrets.token_urlsafe(32))

    def seal(self, api_key: str) -> str:
        return self._fernet.encrypt(api_key.encode()).decode()

    def open(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Could not decrypt the API key for this run") from exc
