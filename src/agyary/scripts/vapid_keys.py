"""Make the key pair for phone notifications (web push), once.

Run on the server and append straight to its settings, so the private key is
never shown on screen or copied anywhere:

    docker compose exec -T app python -m agyary.scripts.vapid_keys >> .env
    docker compose up -d app

It refuses if the app already has keys: a new pair would silently end every
phone's notifications, and each would have to be turned on again.
"""

from __future__ import annotations

import base64
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from agyary.core.config import get_settings


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make() -> tuple[str, str]:
    """(public, private), base64url: the public key as an uncompressed P-256
    point (what a browser's applicationServerKey takes), the private as its
    raw 32 bytes (what pywebpush reads)."""
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64(public), _b64(key.private_numbers().private_value.to_bytes(32, "big"))


def main() -> int:
    settings = get_settings()
    if settings.vapid_public_key.strip() or settings.vapid_private_key.strip():
        print("Phone notification keys are already set; nothing was made.", file=sys.stderr)
        return 1
    public, private = make()
    print()
    print("# Phone notifications (web push), made by agyary.scripts.vapid_keys. Never change them.")
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")
    print("Keys added. Now run: docker compose up -d app", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
