import pytest

from amulio.tokens import InvalidToken, sign, verify


def test_signed_token_round_trip():
    token = sign({"candidate": {"hash": "a" * 32}}, secret="x" * 32, ttl_seconds=60)

    assert verify(token, secret="x" * 32)["candidate"]["hash"] == "a" * 32


def test_signed_token_rejects_another_secret():
    token = sign({"candidate": {"hash": "a" * 32}}, secret="x" * 32, ttl_seconds=60)

    with pytest.raises(InvalidToken):
        verify(token, secret="y" * 32)


def test_signed_token_rejects_expired_payload():
    token = sign({"candidate": {"hash": "a" * 32}}, secret="x" * 32, ttl_seconds=-1)

    with pytest.raises(InvalidToken, match="expired"):
        verify(token, secret="x" * 32)
