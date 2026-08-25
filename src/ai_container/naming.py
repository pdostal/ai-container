"""Random container names and web-mode passwords."""

from __future__ import annotations

import secrets
import string

# Excludes ambiguous characters: 0, 1, i, l, o
_NAME_ALPHABET = "acdefghjkmnpqrstuvwxyz23456789"
_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def random_container_name() -> str:
    suffix = "".join(secrets.choice(_NAME_ALPHABET) for _ in range(3))
    return f"ai-{suffix}"


def random_web_password(length: int = 20) -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
