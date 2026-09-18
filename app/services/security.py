import hashlib
import hmac
import os


def hash_pin(pin: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or os.urandom(8).hex()
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 100_000).hex()
    return salt, digest


def verify_pin(pin: str, salt: str, expected_hash: str) -> bool:
    _, digest = hash_pin(pin, salt)
    return hmac.compare_digest(digest, expected_hash)
