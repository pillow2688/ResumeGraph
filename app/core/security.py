import hashlib
import hmac
import re
import secrets

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

MIN_ADMIN_PASSWORD_LENGTH = 12
MAX_ADMIN_PASSWORD_LENGTH = 128
ACCESS_TOKEN_PREFIX = "rsg_"
_ACCESS_TOKEN_PATTERN = re.compile(r"^rsg_[A-Za-z0-9_-]{22,196}$")

_password_hash = PasswordHash.recommended()


def normalize_admin_username(username: str) -> str:
    return username.strip().lower()


def validate_admin_password(password: str) -> str:
    if not MIN_ADMIN_PASSWORD_LENGTH <= len(password) <= MAX_ADMIN_PASSWORD_LENGTH:
        raise ValueError("Password must be between 12 and 128 characters.")
    return password


def hash_password(password: str) -> str:
    return _password_hash.hash(validate_admin_password(password))


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hash.verify(password, password_hash)
    except UnknownHashError:
        return False


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def generate_access_token() -> str:
    return f"{ACCESS_TOKEN_PREFIX}{secrets.token_urlsafe(24)}"


def digest_access_token(raw_token: str, pepper: str) -> str:
    return hmac.new(
        pepper.encode("utf-8"),
        raw_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def is_access_token_format_valid(raw_token: str) -> bool:
    return _ACCESS_TOKEN_PATTERN.fullmatch(raw_token) is not None


def digest_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
