"""Envelope encryption for the emergency profile.

§"User identity" of the module plan: *"emergency profile เข้ารหัส application-level envelope หรือ
field encryption; key ไม่ได้อยู่ DB เดียวกันใน production"*. This is the envelope form.

Each record gets its own random data key. The payload is sealed with that data key; the data key is
then sealed with a key-encryption key from configuration. Both ciphertexts go in the row, the
key-encryption key does not. Two consequences follow, and they are the reason for the extra step
over sealing the payload directly:

* **Rotation is cheap.** Turning over the key-encryption key means re-wrapping one small data key
  per row, not re-encrypting and rewriting every medical note in the table.
* **A database dump is not enough.** Reading a profile needs the row *and* the environment, which
  live in different places in any deployment worth the name.

AES-256-GCM throughout, so every ciphertext is authenticated. The user id is bound in as additional
authenticated data: a row copied into another user's record fails to decrypt rather than handing
one person's medical details to another.

There is no plaintext fallback anywhere in this module. If no key is configured, sealing raises and
the endpoint reports the feature as unavailable. Storing a medical note unencrypted because the
configuration was incomplete is exactly the failure this exists to prevent.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: AES-256. Anything shorter is rejected when the key is parsed rather than at first use.
KEY_BYTES = 32
#: 96 bits, the size AES-GCM is specified for. A random nonce of this width is safe for the volume
#: of writes this table will ever see.
NONCE_BYTES = 12


class EncryptionNotConfigured(Exception):
    """No key-encryption key is available.

    Raised instead of falling back to plaintext. The caller turns it into an explicit
    "unavailable", which is honest; silently storing a medical note in the clear is not.
    """


class DecryptionFailed(Exception):
    """The ciphertext did not authenticate.

    Means one of: the wrong key version, a tampered row, or a row moved between users. The message
    deliberately does not say which — the distinction is useful to an attacker and not to a user.
    """


@dataclass(frozen=True, slots=True)
class SealedPayload:
    """What gets written to the row. None of it is meaningful without the configured key."""

    ciphertext: bytes
    nonce: bytes
    wrapped_key: bytes
    wrapped_key_nonce: bytes
    key_version: str


@dataclass(frozen=True)
class EnvelopeCipher:
    """Seals and opens payloads under a set of versioned key-encryption keys."""

    #: version -> 32-byte key. More than one so a rotation can still read old rows.
    keys: dict[str, bytes]
    #: The version new writes are sealed under.
    active_version: str

    @classmethod
    def from_config(cls, raw_keys: str | None, active_version: str | None) -> EnvelopeCipher | None:
        """Parse `v1:<base64>,v2:<base64>`, or return None when nothing is configured.

        None rather than an exception: the service must still start and serve health, trips and
        everything else. Only the emergency profile depends on this.
        """
        if not raw_keys:
            return None

        keys: dict[str, bytes] = {}
        for entry in raw_keys.split(","):
            entry = entry.strip()
            if not entry:
                continue
            version, _, encoded = entry.partition(":")
            version = version.strip()
            if not version or not encoded:
                raise ValueError(
                    "Encryption keys must be formatted as `version:base64key`, comma-separated."
                )
            try:
                key = base64.urlsafe_b64decode(encoded.strip() + "=" * (-len(encoded.strip()) % 4))
            except Exception as exc:
                raise ValueError(f"Encryption key {version!r} is not valid base64.") from exc
            if len(key) != KEY_BYTES:
                raise ValueError(
                    f"Encryption key {version!r} is {len(key)} bytes; AES-256 needs {KEY_BYTES}."
                )
            keys[version] = key

        if not keys:
            return None

        # Default to the last declared version, so adding a key to the end of the list is enough to
        # start using it. Being explicit is still better, and the setting allows it.
        version = active_version or list(keys)[-1]
        if version not in keys:
            raise ValueError(
                f"The active key version {version!r} is not among the configured keys "
                f"({sorted(keys)})."
            )
        return cls(keys=keys, active_version=version)

    @staticmethod
    def generate_key() -> str:
        """A fresh base64 key, for `python -m app.cli.generate_key`."""
        return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode().rstrip("=")

    def seal(self, payload: dict[str, Any], *, owner_id: uuid.UUID) -> SealedPayload:
        """Encrypt one profile for one owner."""
        key_encryption_key = self.keys.get(self.active_version)
        if key_encryption_key is None:  # pragma: no cover - from_config guarantees this
            raise EncryptionNotConfigured

        data_key = os.urandom(KEY_BYTES)
        nonce = os.urandom(NONCE_BYTES)
        # sort_keys so the same profile produces the same plaintext length regardless of field
        # order, and separators so no space is wasted on something nobody will read by eye.
        plaintext = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

        associated = self._associated_data(owner_id)
        ciphertext = AESGCM(data_key).encrypt(nonce, plaintext, associated)

        wrapped_key_nonce = os.urandom(NONCE_BYTES)
        wrapped_key = AESGCM(key_encryption_key).encrypt(wrapped_key_nonce, data_key, associated)

        return SealedPayload(
            ciphertext=ciphertext,
            nonce=nonce,
            wrapped_key=wrapped_key,
            wrapped_key_nonce=wrapped_key_nonce,
            key_version=self.active_version,
        )

    def open(self, sealed: SealedPayload, *, owner_id: uuid.UUID) -> dict[str, Any]:
        """Decrypt a profile, or refuse."""
        key_encryption_key = self.keys.get(sealed.key_version)
        if key_encryption_key is None:
            # The row was written under a key this process does not have. Retiring a key while rows
            # still reference it makes them unreadable, so this is a configuration mistake rather
            # than a data problem.
            raise DecryptionFailed(f"no key for version {sealed.key_version!r}")

        associated = self._associated_data(owner_id)
        try:
            data_key = AESGCM(key_encryption_key).decrypt(
                sealed.wrapped_key_nonce, sealed.wrapped_key, associated
            )
            plaintext = AESGCM(data_key).decrypt(sealed.nonce, sealed.ciphertext, associated)
        except InvalidTag as exc:
            raise DecryptionFailed("the payload did not authenticate") from exc

        decoded: dict[str, Any] = json.loads(plaintext)
        return decoded

    def rewrap(self, sealed: SealedPayload, *, owner_id: uuid.UUID) -> SealedPayload:
        """Move a record onto the active key without touching the payload ciphertext.

        This is what makes rotation affordable: only the wrapped data key changes, so rotating
        across a large table is a small update per row rather than a full rewrite.
        """
        if sealed.key_version == self.active_version:
            return sealed

        old_key = self.keys.get(sealed.key_version)
        new_key = self.keys.get(self.active_version)
        if old_key is None or new_key is None:
            raise DecryptionFailed(f"cannot rewrap from {sealed.key_version!r}")

        associated = self._associated_data(owner_id)
        try:
            data_key = AESGCM(old_key).decrypt(
                sealed.wrapped_key_nonce, sealed.wrapped_key, associated
            )
        except InvalidTag as exc:
            raise DecryptionFailed("the wrapped key did not authenticate") from exc

        wrapped_key_nonce = os.urandom(NONCE_BYTES)
        return SealedPayload(
            ciphertext=sealed.ciphertext,
            nonce=sealed.nonce,
            wrapped_key=AESGCM(new_key).encrypt(wrapped_key_nonce, data_key, associated),
            wrapped_key_nonce=wrapped_key_nonce,
            key_version=self.active_version,
        )

    @staticmethod
    def _associated_data(owner_id: uuid.UUID) -> bytes:
        """Bind the ciphertext to its owner.

        Authenticated but not encrypted, so moving a row to another user's record makes the tag
        check fail. Without this, a swapped `user_id` would hand one person's medical details to
        another and nothing would notice.
        """
        return f"emergency_profile:{owner_id}".encode()
