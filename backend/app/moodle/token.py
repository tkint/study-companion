"""Turn whatever the user pasted into ``MOODLE_TOKEN`` into a bare web service token.

Three inputs are accepted, because SSO sites (university login) cannot use a password:

* the token itself, copied from Moodle's *Preferences > Security keys* page
  (``32 hex characters``);
* the ``moodlemobile://token=<base64>`` link the Moodle app SSO launch page redirects to
  (``/admin/tool/mobile/launch.php``), see docs/moodle-token.md;
* just the ``<base64>`` part of that link.

The base64 payload is ``<md5(siteurl + passport)>:::<token>[:::<privatetoken>]``. Only the
token is kept; the private token is discarded. Error messages never include the input.
"""

from __future__ import annotations

import base64
import binascii
import re

# Moodle tokens are 32 hex characters; a launch payload is always longer than 64.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9]{16,64}$")


class TokenFormatError(ValueError):
    """The pasted value is not a token we recognise."""


def _try_decode(payload: str) -> str | None:
    padded = payload + "=" * (-len(payload) % 4)
    try:
        decoded = base64.b64decode(padded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    parts = decoded.split(":::")
    if len(parts) >= 2 and _TOKEN_RE.match(parts[1]):
        return parts[1]
    return None


def _decode_launch_payload(payload: str) -> str:
    payload = payload.split("&", 1)[0].strip()
    # Some browsers append a "/" to custom-scheme links; "/" is also a base64 character,
    # so try the value as-is first.
    for candidate in (payload, payload.rstrip("/")):
        token = _try_decode(candidate)
        if token:
            return token
    raise TokenFormatError(
        "not a token or a moodlemobile://token=... link (see docs/moodle-token.md)"
    )


def parse_pasted_token(value: str | None) -> str:
    """Return the bare token, ``""`` for empty input, or raise TokenFormatError."""
    value = (value or "").strip().strip("'\"").strip()
    if not value:
        return ""
    if "token=" in value:
        return _decode_launch_payload(value.split("token=", 1)[1])
    if _TOKEN_RE.match(value):
        return value
    # Bare base64 payload from the launch link.
    return _decode_launch_payload(value)
