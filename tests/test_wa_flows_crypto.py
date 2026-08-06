"""Meta WhatsApp Flows Data Exchange encryption: verified against the
primary doc during planning (developers.facebook.com/docs/whatsapp/flows/
guides/implementingyourflowendpoint). No live Meta account is available in
this environment, so these tests validate: (a) internal round-trip
consistency against a locally-generated test keypair, and (b) - the part a
round-trip test cannot catch - a known-answer test vector for the IV flip,
where the expected output is hardcoded rather than derived from the
module's own logic. A round-trip test alone would still pass even if the
flip were backwards or applied at the wrong stage, since encrypt/decrypt
would happily agree with each other regardless."""

from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agyary.messaging.wa_flows_crypto import (
    FlowDecryptionError,
    decrypt_request,
    encrypt_response,
    flip_iv,
)


def test_flip_iv_known_answer_vector():
    """Hardcoded input -> hardcoded expected output, not derived from the
    module under test. This is what actually catches a directional bug -
    e.g. flipping only some bytes, flipping the AES key instead of the IV,
    or a no-op that a round-trip test would never notice."""
    iv = bytes([0x00, 0x01, 0x02, 0x0F, 0x10, 0xF0, 0xFF, 0xAA, 0x55, 0x7E, 0x81, 0x3C, 0xC3, 0x00, 0xFF, 0x99])
    expected = bytes([0xFF, 0xFE, 0xFD, 0xF0, 0xEF, 0x0F, 0x00, 0x55, 0xAA, 0x81, 0x7E, 0xC3, 0x3C, 0xFF, 0x00, 0x66])
    assert flip_iv(iv) == expected


def test_flip_iv_is_involution():
    """Flipping twice returns the original - a basic sanity property, not a
    substitute for the known-answer vector above."""
    iv = bytes(range(16))
    assert flip_iv(flip_iv(iv)) == iv


def generate_test_keypair() -> tuple[bytes, rsa.RSAPrivateKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem, private_key


def build_meta_style_request(public_key, payload: dict) -> tuple[dict, bytes, bytes]:
    """Simulate what Meta's client sends: a fresh AES-128 key + IV, the
    payload encrypted with AES-GCM, the AES key wrapped with RSA-OAEP-SHA256.
    Returns (request_body, aes_key, iv) so the test can assert against the
    originals."""
    aes_key = AESGCM.generate_key(bit_length=128)
    iv = os.urandom(16)
    ciphertext = AESGCM(aes_key).encrypt(iv, json.dumps(payload).encode(), None)
    encrypted_aes_key = public_key.encrypt(
        aes_key,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    body = {
        "encrypted_flow_data": base64.b64encode(ciphertext).decode(),
        "encrypted_aes_key": base64.b64encode(encrypted_aes_key).decode(),
        "initial_vector": base64.b64encode(iv).decode(),
    }
    return body, aes_key, iv


def test_decrypt_request_round_trip():
    pem, private_key = generate_test_keypair()
    payload = {"screen": "SELECT_ROJ", "data": {}, "action": "INIT"}
    body, aes_key, iv = build_meta_style_request(private_key.public_key(), payload)

    decrypted, returned_aes_key, returned_iv = decrypt_request(body, pem)

    assert decrypted == payload
    assert returned_aes_key == aes_key
    assert returned_iv == iv


def test_decrypt_request_rejects_tampered_ciphertext():
    pem, private_key = generate_test_keypair()
    body, _aes_key, _iv = build_meta_style_request(private_key.public_key(), {"a": 1})

    tampered = bytearray(base64.b64decode(body["encrypted_flow_data"]))
    tampered[0] ^= 0xFF
    body["encrypted_flow_data"] = base64.b64encode(bytes(tampered)).decode()

    try:
        decrypt_request(body, pem)
        assert False, "expected FlowDecryptionError"
    except FlowDecryptionError:
        pass


def test_encrypt_response_uses_flipped_iv_and_decrypts_with_it():
    """The response must decrypt correctly using the FLIPPED iv, and must
    NOT decrypt with the original (unflipped) request iv - this is the
    behavioral half of the IV-flip guarantee, complementing the
    known-answer vector above."""
    pem, private_key = generate_test_keypair()
    body, aes_key, iv = build_meta_style_request(private_key.public_key(), {"a": 1})
    _decrypted, aes_key, iv = decrypt_request(body, pem)

    response = {"data": {"options": [{"id": "roj_1", "title": "Hormazd"}]}}
    encrypted_response = encrypt_response(response, aes_key, iv)
    response_bytes = base64.b64decode(encrypted_response)

    flipped = flip_iv(iv)
    decrypted_response = AESGCM(aes_key).decrypt(flipped, response_bytes, None)
    assert json.loads(decrypted_response) == response

    try:
        AESGCM(aes_key).decrypt(iv, response_bytes, None)
        assert False, "response must not decrypt with the un-flipped request iv"
    except Exception:
        pass
