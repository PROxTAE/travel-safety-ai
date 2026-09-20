"""Envelope encryption.

Real AES-GCM, no database. The properties under test are the ones that make the difference between
"encrypted" as a checkbox and encrypted as a defence: that ciphertext bound to one user cannot be
read as another, that tampering is detected rather than silently accepted, and that rotating a key
does not require rewriting every payload.
"""

from __future__ import annotations

import base64
import os
import uuid

import pytest

from app.security.envelope import (
    KEY_BYTES,
    DecryptionFailed,
    EnvelopeCipher,
    SealedPayload,
)

PAYLOAD = {
    "blood_type": "O+",
    "allergies": ["penicillin"],
    "medical_notes": "Carries an adrenaline auto-injector.",
    "contacts": [{"name": "Next of kin", "phone": "+66000000000"}],
}


def key() -> str:
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode().rstrip("=")


@pytest.fixture
def cipher() -> EnvelopeCipher:
    built = EnvelopeCipher.from_config(f"v1:{key()}", None)
    assert built is not None
    return built


@pytest.fixture
def owner() -> uuid.UUID:
    return uuid.uuid4()


# --- the basics ---------------------------------------------------------------------------------


def test_a_sealed_payload_comes_back_unchanged(cipher: EnvelopeCipher, owner: uuid.UUID) -> None:
    sealed = cipher.seal(PAYLOAD, owner_id=owner)

    assert cipher.open(sealed, owner_id=owner) == PAYLOAD


def test_the_ciphertext_does_not_contain_the_plaintext(
    cipher: EnvelopeCipher, owner: uuid.UUID
) -> None:
    """The obvious check, and worth making: a bug that stored the payload beside the ciphertext
    would pass every round-trip test."""
    sealed = cipher.seal(PAYLOAD, owner_id=owner)

    assert b"penicillin" not in sealed.ciphertext
    assert b"adrenaline" not in sealed.ciphertext
    assert b"penicillin" not in sealed.wrapped_key


def test_sealing_the_same_payload_twice_gives_different_ciphertext(
    cipher: EnvelopeCipher, owner: uuid.UUID
) -> None:
    """A fresh data key and nonce each time, so two people with identical profiles — or one person
    saving twice — do not produce matching rows that reveal that fact."""
    first = cipher.seal(PAYLOAD, owner_id=owner)
    second = cipher.seal(PAYLOAD, owner_id=owner)

    assert first.ciphertext != second.ciphertext
    assert first.wrapped_key != second.wrapped_key
    assert first.nonce != second.nonce


def test_an_empty_profile_still_seals(cipher: EnvelopeCipher, owner: uuid.UUID) -> None:
    sealed = cipher.seal({}, owner_id=owner)

    assert cipher.open(sealed, owner_id=owner) == {}


def test_unicode_survives_the_round_trip(cipher: EnvelopeCipher, owner: uuid.UUID) -> None:
    """Thai is a first-class language for this product, and a sealed blob that mangles it is
    worse than one that fails outright."""
    payload = {"medical_notes": "แพ้ยาเพนิซิลลิน", "allergies": ["ถั่วลิสง"]}

    assert cipher.open(cipher.seal(payload, owner_id=owner), owner_id=owner) == payload


# --- the properties that matter -------------------------------------------------------------------


def test_a_row_cannot_be_read_as_another_user(cipher: EnvelopeCipher) -> None:
    """The reason the owner id is bound in as associated data.

    Without it, swapping `user_id` on a row — by a bug, a bad migration or an attacker with write
    access — would hand one person's medical details to another, and nothing would notice.
    """
    alice, bob = uuid.uuid4(), uuid.uuid4()
    sealed = cipher.seal(PAYLOAD, owner_id=alice)

    with pytest.raises(DecryptionFailed):
        cipher.open(sealed, owner_id=bob)


def test_tampering_with_the_ciphertext_is_detected(
    cipher: EnvelopeCipher, owner: uuid.UUID
) -> None:
    sealed = cipher.seal(PAYLOAD, owner_id=owner)
    flipped = bytearray(sealed.ciphertext)
    flipped[0] ^= 0x01

    with pytest.raises(DecryptionFailed):
        cipher.open(
            SealedPayload(
                ciphertext=bytes(flipped),
                nonce=sealed.nonce,
                wrapped_key=sealed.wrapped_key,
                wrapped_key_nonce=sealed.wrapped_key_nonce,
                key_version=sealed.key_version,
            ),
            owner_id=owner,
        )


def test_tampering_with_the_wrapped_key_is_detected(
    cipher: EnvelopeCipher, owner: uuid.UUID
) -> None:
    sealed = cipher.seal(PAYLOAD, owner_id=owner)
    flipped = bytearray(sealed.wrapped_key)
    flipped[0] ^= 0x01

    with pytest.raises(DecryptionFailed):
        cipher.open(
            SealedPayload(
                ciphertext=sealed.ciphertext,
                nonce=sealed.nonce,
                wrapped_key=bytes(flipped),
                wrapped_key_nonce=sealed.wrapped_key_nonce,
                key_version=sealed.key_version,
            ),
            owner_id=owner,
        )


def test_a_different_key_cannot_open_the_row(owner: uuid.UUID) -> None:
    """A database dump on its own is not enough."""
    one = EnvelopeCipher.from_config(f"v1:{key()}", None)
    other = EnvelopeCipher.from_config(f"v1:{key()}", None)
    assert one is not None and other is not None

    with pytest.raises(DecryptionFailed):
        other.open(one.seal(PAYLOAD, owner_id=owner), owner_id=owner)


# --- rotation -------------------------------------------------------------------------------------


def test_an_old_row_still_opens_after_a_new_key_is_added(owner: uuid.UUID) -> None:
    """Adding a key must not lock anyone out of the data they already stored."""
    first_key = key()
    before = EnvelopeCipher.from_config(f"v1:{first_key}", None)
    assert before is not None
    sealed = before.seal(PAYLOAD, owner_id=owner)

    after = EnvelopeCipher.from_config(f"v1:{first_key},v2:{key()}", "v2")
    assert after is not None

    assert after.open(sealed, owner_id=owner) == PAYLOAD


def test_new_writes_use_the_active_key(owner: uuid.UUID) -> None:
    rotated = EnvelopeCipher.from_config(f"v1:{key()},v2:{key()}", "v2")
    assert rotated is not None

    assert rotated.seal(PAYLOAD, owner_id=owner).key_version == "v2"


def test_rewrapping_moves_the_key_without_touching_the_payload(owner: uuid.UUID) -> None:
    """The point of the envelope: rotation is one small update per row, not a full rewrite."""
    first_key = key()
    before = EnvelopeCipher.from_config(f"v1:{first_key}", None)
    assert before is not None
    sealed = before.seal(PAYLOAD, owner_id=owner)

    after = EnvelopeCipher.from_config(f"v1:{first_key},v2:{key()}", "v2")
    assert after is not None
    rewrapped = after.rewrap(sealed, owner_id=owner)

    assert rewrapped.key_version == "v2"
    assert rewrapped.ciphertext == sealed.ciphertext, "the payload was re-encrypted unnecessarily"
    assert rewrapped.wrapped_key != sealed.wrapped_key
    assert after.open(rewrapped, owner_id=owner) == PAYLOAD


def test_rewrapping_a_current_row_is_a_no_op(cipher: EnvelopeCipher, owner: uuid.UUID) -> None:
    sealed = cipher.seal(PAYLOAD, owner_id=owner)

    assert cipher.rewrap(sealed, owner_id=owner) is sealed


def test_a_row_sealed_under_a_retired_key_fails_loudly(owner: uuid.UUID) -> None:
    """Dropping a key while rows still reference it makes them unreadable. That is a configuration
    mistake, and it must not look like a missing record."""
    old = EnvelopeCipher.from_config(f"v1:{key()}", None)
    assert old is not None
    sealed = old.seal(PAYLOAD, owner_id=owner)

    retired = EnvelopeCipher.from_config(f"v2:{key()}", "v2")
    assert retired is not None

    with pytest.raises(DecryptionFailed):
        retired.open(sealed, owner_id=owner)


# --- configuration --------------------------------------------------------------------------------


def test_no_configuration_means_no_cipher_rather_than_an_error() -> None:
    """The service still starts and serves everything else; only this feature is unavailable."""
    assert EnvelopeCipher.from_config(None, None) is None
    assert EnvelopeCipher.from_config("", None) is None


def test_a_short_key_is_rejected_when_it_is_parsed() -> None:
    """At startup, where someone is watching — not on the first request that needs it."""
    short = base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip("=")

    with pytest.raises(ValueError, match="AES-256 needs"):
        EnvelopeCipher.from_config(f"v1:{short}", None)


@pytest.mark.parametrize("malformed", ["v1", "v1:", ":abc", "v1:not base64!!"])
def test_a_malformed_key_entry_is_rejected(malformed: str) -> None:
    with pytest.raises(ValueError, match="(?i)base64|formatted"):
        EnvelopeCipher.from_config(malformed, None)


def test_an_active_version_that_does_not_exist_is_rejected() -> None:
    """Otherwise every write would fail at runtime with a confusing error."""
    with pytest.raises(ValueError, match="not among the configured keys"):
        EnvelopeCipher.from_config(f"v1:{key()}", "v9")


def test_the_active_version_defaults_to_the_last_listed() -> None:
    cipher = EnvelopeCipher.from_config(f"v1:{key()},v2:{key()}", None)
    assert cipher is not None

    assert cipher.active_version == "v2"


def test_generated_keys_are_the_right_size_and_unique() -> None:
    first, second = EnvelopeCipher.generate_key(), EnvelopeCipher.generate_key()

    assert first != second
    for generated in (first, second):
        decoded = base64.urlsafe_b64decode(generated + "=" * (-len(generated) % 4))
        assert len(decoded) == KEY_BYTES
