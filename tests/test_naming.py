from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_container.naming import (
    _NAME_ALPHABET,
    _PASSWORD_ALPHABET,
    random_container_name,
    random_web_password,
)

_NAME_RE = re.compile(rf"^ai-[{re.escape(_NAME_ALPHABET)}]{{3}}$")


def test_container_name_format() -> None:
    name = random_container_name()
    assert _NAME_RE.match(name), name


def test_container_name_excludes_ambiguous_characters() -> None:
    assert not set("01ilo") & set(_NAME_ALPHABET)


@given(st.integers(min_value=1, max_value=64))
@settings(max_examples=25)
def test_web_password_length_and_alphabet(length: int) -> None:
    password = random_web_password(length)
    assert len(password) == length
    assert set(password) <= set(_PASSWORD_ALPHABET)


def test_default_password_length_is_twenty() -> None:
    assert len(random_web_password()) == 20


def test_names_and_passwords_are_not_constant() -> None:
    names = {random_container_name() for _ in range(50)}
    passwords = {random_web_password() for _ in range(50)}
    assert len(names) > 1
    assert len(passwords) > 1
