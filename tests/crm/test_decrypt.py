import base64
import json
import os

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from event_users.crm.client import EncryptedUsersPayload
from event_users.crm.sync import decrypt_payload


KEY = bytes(range(32))


def encrypt(users: list[dict], key: bytes = KEY) -> EncryptedUsersPayload:
    iv = os.urandom(16)
    padder = PKCS7(128).padder()
    padded = padder.update(json.dumps(users).encode()) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return EncryptedUsersPayload(
        encrypted_data=base64.b64encode(ciphertext).decode(),
        iv=base64.b64encode(iv).decode(),
        total=len(users),
        page=1,
        page_size=100,
    )


def test_decrypt_roundtrip() -> None:
    payload = encrypt(
        [
            {
                "email": "a@b.c",
                "name": "Ann",
                "role": "client",
                "time_zone": "Europe/Moscow",
                "contacts": [{"channel": "telegram", "contact_id": "123"}],
            },
            {"email": "x@y.z", "role": "organizer"},
        ],
    )
    users = decrypt_payload(payload, KEY)
    assert len(users) == 2
    assert users[0].email == "a@b.c"
    assert users[0].contacts is not None
    assert users[0].contacts[0].channel == "telegram"
    assert users[1].name is None
    assert users[1].contacts == []


def test_decrypt_with_no_contacts_key() -> None:
    payload = encrypt([{"email": "a@b.c", "role": "client", "contacts": None}])
    users = decrypt_payload(payload, KEY)
    assert users[0].contacts == []


def test_decrypt_wrong_key_raises() -> None:
    payload = encrypt([{"email": "a@b.c", "role": "client"}])
    with pytest.raises(Exception):  # noqa: B017, PT011 — exact type asserted in test_sync error handling
        decrypt_payload(payload, bytes(reversed(range(32))))
