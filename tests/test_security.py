import importlib
import importlib.util

import pytest


def load_security():
    assert importlib.util.find_spec("app.core.security") is not None, "security module must exist"
    return importlib.import_module("app.core.security")


def test_password_hash_uses_argon2_without_containing_plaintext() -> None:
    security = load_security()
    password = "correct horse battery staple"

    password_hash = security.hash_password(password)

    assert password_hash.startswith("$argon2")
    assert password not in password_hash
    assert security.verify_password(password, password_hash) is True


def test_password_verification_rejects_wrong_password_and_unknown_hash() -> None:
    security = load_security()
    password_hash = security.hash_password("correct horse battery staple")

    assert security.verify_password("wrong password", password_hash) is False
    assert security.verify_password("any password", "not-a-supported-hash") is False


def test_admin_username_is_trimmed_and_lowercased() -> None:
    security = load_security()

    assert security.normalize_admin_username("  Admin.User  ") == "admin.user"


@pytest.mark.parametrize("length", [12, 128])
def test_admin_password_accepts_supported_lengths(length: int) -> None:
    security = load_security()
    password = "x" * length

    assert security.validate_admin_password(password) == password


@pytest.mark.parametrize("length", [11, 129])
def test_admin_password_rejects_unsupported_lengths(length: int) -> None:
    security = load_security()

    with pytest.raises(ValueError, match="between 12 and 128 characters"):
        security.validate_admin_password("x" * length)


def test_session_tokens_are_high_entropy_and_digest_hides_the_raw_value() -> None:
    security = load_security()

    first_token = security.generate_session_token()
    second_token = security.generate_session_token()
    digest = security.digest_secret(first_token)

    assert first_token != second_token
    assert len(first_token) >= 43
    assert len(digest) == 64
    assert first_token not in digest


def test_access_tokens_are_prefixed_high_entropy_and_hmac_digested() -> None:
    security = load_security()
    pepper = "fictional-pepper-used-only-in-tests"

    first_token = security.generate_access_token()
    second_token = security.generate_access_token()
    digest = security.digest_access_token(first_token, pepper)

    assert first_token.startswith("rsg_")
    assert first_token != second_token
    assert len(first_token.removeprefix("rsg_")) >= 22
    assert len(digest) == 64
    assert first_token != digest
    assert first_token not in digest
    assert security.digest_access_token(first_token, "different-fictional-pepper") != digest


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("rsg_abcdefghijklmnopqrstuv", True),
        ("rsg_abc", False),
        ("not-rsg_abcdefghijklmnopqrstuv", False),
        ("rsg_invalid.token.characters", False),
    ],
)
def test_access_token_format_validation(value: str, expected: bool) -> None:
    security = load_security()

    assert security.is_access_token_format_valid(value) is expected
