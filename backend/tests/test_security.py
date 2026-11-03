"""Tests for password hashing, JWT access tokens and refresh tokens."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Settings, get_settings
from app.core.security import (
    BCRYPT_MAX_PASSWORD_BYTES,
    PasswordTooLongError,
    TokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    simulate_password_check,
    verify_password,
)

# ------------------------------------------------------------------------ passwords


def test_hash_is_not_the_plain_password_and_verifies() -> None:
    hashed = hash_password("S3cure-Passw0rd!")

    assert hashed != "S3cure-Passw0rd!"
    assert hashed.startswith("$2b$")  # bcrypt
    assert verify_password("S3cure-Passw0rd!", hashed) is True


def test_same_password_gives_different_hashes() -> None:
    # A random salt is added to every hash.
    assert hash_password("same-password") != hash_password("same-password")


def test_wrong_password_is_rejected() -> None:
    hashed = hash_password("correct-password")

    assert verify_password("wrong-password", hashed) is False
    assert verify_password("Correct-password", hashed) is False  # case-sensitive
    assert verify_password("", hashed) is False


def test_unicode_password_round_trip() -> None:
    hashed = hash_password("pässwörd-密码-🔒")

    assert verify_password("pässwörd-密码-🔒", hashed) is True


def test_password_over_72_bytes_is_rejected() -> None:
    with pytest.raises(PasswordTooLongError):
        hash_password("a" * (BCRYPT_MAX_PASSWORD_BYTES + 1))
    # 72 bytes exactly is fine
    assert verify_password("a" * 72, hash_password("a" * 72)) is True
    # Multi-byte characters count as several bytes ("é" is 2 bytes in UTF-8)
    with pytest.raises(PasswordTooLongError):
        hash_password("é" * 37)


def test_verify_never_raises_on_bad_input() -> None:
    assert verify_password("x" * 100, hash_password("short")) is False
    assert verify_password("anything", "not-a-valid-hash") is False


def test_simulate_password_check_runs() -> None:
    simulate_password_check()  # must not raise


# -------------------------------------------------------------------- access tokens


def _encode(claims: dict[str, object], key: str | None = None, algorithm: str = "HS256") -> str:
    settings = get_settings()
    return jwt.encode(claims, key or settings.secret_key, algorithm=algorithm)


def _valid_claims(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": "42",
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "iss": get_settings().jwt_issuer,
        "jti": "abc123",
    }
    claims.update(overrides)
    return claims


def test_access_token_round_trip() -> None:
    token = create_access_token(42)
    payload = decode_access_token(token)

    assert payload.user_id == 42
    assert len(payload.jti) == 32
    lifetime = payload.expires_at - payload.issued_at
    assert lifetime == timedelta(minutes=get_settings().access_token_expire_minutes)


def test_each_access_token_is_unique() -> None:
    assert (
        decode_access_token(create_access_token(1)).jti
        != decode_access_token(create_access_token(1)).jti
    )


def test_expired_access_token_is_rejected() -> None:
    token = create_access_token(42, expires_delta=timedelta(seconds=-1))

    with pytest.raises(TokenError, match="expired"):
        decode_access_token(token)


def test_tampered_access_token_is_rejected() -> None:
    token = create_access_token(42)
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[:-2]}{'AA' if signature[-2:] != 'AA' else 'BB'}"

    with pytest.raises(TokenError):
        decode_access_token(tampered)


def test_token_signed_with_another_key_is_rejected() -> None:
    token = _encode(_valid_claims(), key="some-other-secret-key-that-is-long-enough")

    with pytest.raises(TokenError):
        decode_access_token(token)


def test_unsigned_alg_none_token_is_rejected() -> None:
    token = jwt.encode(_valid_claims(), key=None, algorithm="none")

    with pytest.raises(TokenError):
        decode_access_token(token)


def test_wrong_issuer_is_rejected() -> None:
    with pytest.raises(TokenError):
        decode_access_token(_encode(_valid_claims(iss="someone-else")))


def test_wrong_token_type_is_rejected() -> None:
    with pytest.raises(TokenError, match="type"):
        decode_access_token(_encode(_valid_claims(type="refresh")))


@pytest.mark.parametrize("missing", ["sub", "type", "exp", "iat", "iss", "jti"])
def test_token_missing_required_claim_is_rejected(missing: str) -> None:
    claims = _valid_claims()
    del claims[missing]

    with pytest.raises(TokenError):
        decode_access_token(_encode(claims))


def test_non_numeric_subject_is_rejected() -> None:
    with pytest.raises(TokenError, match="subject"):
        decode_access_token(_encode(_valid_claims(sub="not-a-number")))


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "Bearer xyz"])
def test_garbage_is_rejected(garbage: str) -> None:
    with pytest.raises(TokenError):
        decode_access_token(garbage)


def test_extra_claims_cannot_override_reserved_claims() -> None:
    token = create_access_token(7, extra_claims={"sub": "999", "type": "refresh", "scope": "x"})
    payload = decode_access_token(token)

    assert payload.user_id == 7  # reserved claims always win


# ------------------------------------------------------------------- refresh tokens


def test_refresh_token_is_random_and_hashed() -> None:
    first = generate_refresh_token()
    second = generate_refresh_token()

    assert first.token != second.token
    assert len(first.token) >= 64
    assert len(first.token_hash) == 64  # SHA-256 hex
    assert first.token_hash == hash_refresh_token(first.token)
    assert first.token not in first.token_hash


def test_refresh_token_expiry_uses_settings() -> None:
    before = datetime.now(UTC)
    new_token = generate_refresh_token()

    expected = before + timedelta(days=get_settings().refresh_token_expire_days)
    assert abs((new_token.expires_at - expected).total_seconds()) < 5


# ------------------------------------------------------------------------- settings


def test_default_secret_allowed_in_development_and_test() -> None:
    assert Settings(app_env="development").secret_key
    assert Settings(app_env="test").secret_key


def test_default_secret_refused_in_production() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(app_env="production")


def test_short_secret_refused_in_production() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(app_env="production", secret_key="too-short")


def test_strong_secret_accepted_in_production() -> None:
    settings = Settings(app_env="production", secret_key="x" * 64)

    assert settings.app_env == "production"
