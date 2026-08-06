"""Meta WhatsApp Flows Data Exchange encryption.

Scheme verified against Meta's primary doc, fetched directly while building
this module (not a derived/secondary source):
developers.facebook.com/docs/whatsapp/flows/guides/implementingyourflowendpoint

- AES key: unwrapped via RSA/ECB/OAEPWithSHA-256AndMGF1Padding (SHA-256 for
  both the OAEP hash and the MGF1 mask), base64-encoded in the request's
  `encrypted_aes_key` field.
- Body: AES-GCM, 128-bit key, IV taken from the request's base64
  `initial_vector`, 128-bit auth tag appended to the end of the ciphertext.
- Response: IV is the request IV with every byte inverted (XOR 0xFF)
  before AES-GCM re-encryption; tag appended; the whole thing is
  base64-encoded and returned as plain text (not wrapped in JSON).
- Decryption failure -> the endpoint must return HTTP 421, not 200/500
  (same doc: "If a request cannot be decrypted, the endpoint should return
  HTTP 421 response status code"), so the client knows to refresh its
  public key. The route in api/routes/whatsapp.py is responsible for
  translating FlowDecryptionError into that status; this module only
  raises it.

This is the one piece of the whole redesign that cannot be verified live in
this session - no real Meta Business Account, no real Flow registration.
The tests validate the round-trip is internally consistent AND include a
known-answer test vector for the IV flip specifically (a fixed IV with the
expected inverted bytes hardcoded) - a round-trip test alone would still
pass if the flip were backwards or applied at the wrong stage, since it
would happily decrypt its own mistake.
"""

from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FLOW_ENDPOINT_ERROR_STATUS = 421  # Meta's required status on decrypt failure


class FlowDecryptionError(Exception):
    """The request could not be decrypted - wrong/rotated key or a
    malformed payload. Callers (the data-exchange route) must respond with
    FLOW_ENDPOINT_ERROR_STATUS (421), not a generic 4xx/5xx."""


def flip_iv(iv: bytes) -> bytes:
    """Invert every byte of the request IV (XOR 0xFF), producing the IV
    Meta requires for the response. The one transform a plain
    encrypt-then-decrypt round-trip test can't catch if implemented
    backwards - it would happily decrypt its own mistake either way."""
    return bytes(b ^ 0xFF for b in iv)


def decrypt_request(body: dict, private_key_pem: bytes) -> tuple[dict, bytes, bytes]:
    """Decrypt an inbound Flows data-exchange request.

    Returns (decrypted_payload, aes_key, request_iv). The caller passes
    aes_key and request_iv (NOT pre-flipped) to encrypt_response, which
    applies the flip itself.
    """
    try:
        private_key = serialization.load_pem_private_key(private_key_pem, password=None)
        aes_key = private_key.decrypt(
            base64.b64decode(body["encrypted_aes_key"]),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        iv = base64.b64decode(body["initial_vector"])
        flow_data = base64.b64decode(body["encrypted_flow_data"])
        plaintext = AESGCM(aes_key).decrypt(iv, flow_data, None)
        return json.loads(plaintext), aes_key, iv
    except Exception as exc:
        raise FlowDecryptionError(str(exc)) from exc


def encrypt_response(response: dict, aes_key: bytes, request_iv: bytes) -> str:
    """Encrypt an outbound Flows data-exchange response body.

    `request_iv` is the IV from the decrypted request (not yet flipped) -
    this function performs the flip, matching Meta's documented
    response-IV transform, and returns the base64 plain-text body Meta
    expects (not JSON-wrapped).
    """
    response_iv = flip_iv(request_iv)
    plaintext = json.dumps(response).encode()
    ciphertext = AESGCM(aes_key).encrypt(response_iv, plaintext, None)
    return base64.b64encode(ciphertext).decode()
