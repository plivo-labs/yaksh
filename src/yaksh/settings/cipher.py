"""Encryption of the secrets stored with the settings: AES-256-GCM under a key derived from
YAKSH_ENCRYPTION_KEY. A database dump without that key reveals no secret."""

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

FORMAT = 1
"""The first byte of every stored value, so a later key or algorithm can be told apart."""
NONCE_BYTES = 12
MIN_KEY_CHARS = 32
KEY_INFO = b"yaksh settings secrets"


class SecretUnreadableError(Exception):
    """A stored secret cannot be decrypted: YAKSH_ENCRYPTION_KEY is not the key it was saved
    with, or the stored value was changed."""


class Cipher:
    def __init__(self, encryption_key: str) -> None:
        if len(encryption_key) < MIN_KEY_CHARS:
            raise ValueError(f"YAKSH_ENCRYPTION_KEY must be at least {MIN_KEY_CHARS} characters")
        key = HKDF(algorithm=SHA256(), length=32, salt=None, info=KEY_INFO).derive(
            encryption_key.encode()
        )
        self._aead = AESGCM(key)

    def encrypt(self, name: str, value: str) -> str:
        """The value sealed to its setting's name: it cannot be moved to another setting."""
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, value.encode(), name.encode())
        return base64.b64encode(bytes([FORMAT]) + nonce + sealed).decode()

    def decrypt(self, name: str, stored: str) -> str:
        try:
            raw = base64.b64decode(stored, validate=True)
        except binascii.Error as error:
            raise SecretUnreadableError(f"{name}: the stored value is not valid") from error
        if not raw or raw[0] != FORMAT:
            raise SecretUnreadableError(f"{name}: the stored value has an unknown format")
        nonce, sealed = raw[1 : 1 + NONCE_BYTES], raw[1 + NONCE_BYTES :]
        try:
            return self._aead.decrypt(nonce, sealed, name.encode()).decode()
        except InvalidTag as error:
            raise SecretUnreadableError(
                f"{name}: cannot decrypt it; YAKSH_ENCRYPTION_KEY is not the key it was saved with"
            ) from error
