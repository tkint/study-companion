"""Standard-library crypto helpers: password hashing and encryption of secrets at rest.

* Passwords: scrypt (``hashlib.scrypt``) with a random salt.
* Secrets in the database (the Moodle token): encrypt-then-MAC with keys derived from
  SECRET_KEY. The keystream is HMAC-SHA256 in counter mode over a random 16-byte nonce,
  and an HMAC-SHA256 tag over version, nonce and ciphertext is checked (in constant time)
  before decrypting. Rotating SECRET_KEY makes stored secrets unreadable, so they have to
  be entered again on the settings page.

No third-party dependency is needed for this; if one is ever approved, ``cryptography``'s
Fernet would be a drop-in replacement behind the same two functions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_VERSION = b"v1"
_NONCE = 16
_TAG = 32

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


class DecryptError(ValueError):
    """The value was not encrypted with the current SECRET_KEY, or was tampered with."""


def _keys(secret_key: str) -> tuple[bytes, bytes]:
    master = secret_key.encode()
    enc = hmac.new(master, b"study-companion/secret-box/enc/v1", hashlib.sha256).digest()
    mac = hmac.new(master, b"study-companion/secret-box/mac/v1", hashlib.sha256).digest()
    return enc, mac


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def encrypt_secret(secret_key: str, plaintext: str) -> str:
    enc, mac = _keys(secret_key)
    nonce = secrets.token_bytes(_NONCE)
    data = plaintext.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(data, _keystream(enc, nonce, len(data))))
    tag = hmac.new(mac, _VERSION + nonce + ct, hashlib.sha256).digest()
    return _VERSION.decode() + ":" + base64.urlsafe_b64encode(nonce + ct + tag).decode()


def decrypt_secret(secret_key: str, token: str) -> str:
    version, _, body = (token or "").partition(":")
    if version.encode() != _VERSION or not body:
        raise DecryptError("unknown format")
    try:
        raw = base64.urlsafe_b64decode(body.encode())
    except ValueError:
        raise DecryptError("bad encoding") from None
    if len(raw) < _NONCE + _TAG:
        raise DecryptError("too short")
    nonce, ct, tag = raw[:_NONCE], raw[_NONCE:-_TAG], raw[-_TAG:]
    enc, mac = _keys(secret_key)
    expected = hmac.new(mac, _VERSION + nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise DecryptError("authentication failed")
    data = bytes(a ^ b for a, b in zip(ct, _keystream(enc, nonce, len(ct))))
    return data.decode("utf-8")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    b64 = base64.urlsafe_b64encode
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(stored: str, password: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.urlsafe_b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.urlsafe_b64decode(salt),
            n=int(n), r=int(r), p=int(p), dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, actual)
