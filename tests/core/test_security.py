"""Tests for security implementations: OpenSecurity, ACLSecurity, JWTChannelSecurity."""

import time

import pytest

from sssn.core.security import ACLSecurity, JWTChannelSecurity, OpenSecurity


# ---------------------------------------------------------------------------
# OpenSecurity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_security_authenticate():
    sec = OpenSecurity()
    assert await sec.authenticate("any-token") == "any-token"


@pytest.mark.asyncio
async def test_open_security_allows_all():
    sec = OpenSecurity()
    assert await sec.authorize_read("anyone", "ch") is True
    assert await sec.authorize_write("anyone", "ch") is True
    assert await sec.authorize_admin("anyone", "ch") is True


@pytest.mark.asyncio
async def test_open_security_generate_token():
    sec = OpenSecurity()
    token = await sec.generate_token("sys-a", "read")
    assert token == "sys-a"


# ---------------------------------------------------------------------------
# ACLSecurity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acl_grant_read():
    sec = ACLSecurity()
    sec.grant("sys-a", "read")
    assert await sec.authorize_read("sys-a", "ch") is True
    assert await sec.authorize_write("sys-a", "ch") is False
    assert await sec.authorize_admin("sys-a", "ch") is False


@pytest.mark.asyncio
async def test_acl_grant_write_implies_read():
    sec = ACLSecurity()
    sec.grant("sys-a", "write")
    assert await sec.authorize_read("sys-a", "ch") is True
    assert await sec.authorize_write("sys-a", "ch") is True
    assert await sec.authorize_admin("sys-a", "ch") is False


@pytest.mark.asyncio
async def test_acl_grant_admin_implies_all():
    sec = ACLSecurity()
    sec.grant("sys-a", "admin")
    assert await sec.authorize_read("sys-a", "ch") is True
    assert await sec.authorize_write("sys-a", "ch") is True
    assert await sec.authorize_admin("sys-a", "ch") is True


@pytest.mark.asyncio
async def test_acl_revoke():
    sec = ACLSecurity()
    sec.grant("sys-a", "admin")
    sec.revoke("sys-a")
    assert await sec.authorize_read("sys-a", "ch") is False


@pytest.mark.asyncio
async def test_acl_unknown_denied():
    sec = ACLSecurity()
    assert await sec.authorize_read("unknown", "ch") is False


def test_acl_invalid_role():
    sec = ACLSecurity()
    with pytest.raises(ValueError):
        sec.grant("sys-a", "superuser")


@pytest.mark.asyncio
async def test_acl_constructor_lists():
    sec = ACLSecurity(read=["r1"], write=["w1"], admin=["a1"])
    assert await sec.authorize_read("r1", "ch") is True
    assert await sec.authorize_write("r1", "ch") is False
    assert await sec.authorize_write("w1", "ch") is True
    assert await sec.authorize_admin("a1", "ch") is True


@pytest.mark.asyncio
async def test_acl_generate_token_grants_role():
    sec = ACLSecurity()
    token = await sec.generate_token("sys-a", "write")
    assert token == "sys-a"
    assert await sec.authorize_write("sys-a", "ch") is True


# ---------------------------------------------------------------------------
# JWTChannelSecurity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jwt_generate_and_authenticate():
    sec = JWTChannelSecurity(secret="test-secret-that-is-long-enough-32b")
    token = await sec.generate_token("sys-a", "write")
    system_id = await sec.authenticate(token)
    assert system_id == "sys-a"


@pytest.mark.asyncio
async def test_jwt_authenticate_invalid_token():
    sec = JWTChannelSecurity(secret="test-secret-that-is-long-enough-32b")
    result = await sec.authenticate("not-a-jwt")
    assert result is None


@pytest.mark.asyncio
async def test_jwt_local_always_allowed():
    """Local (in-process) authorize_* always return True."""
    sec = JWTChannelSecurity(secret="test-secret-that-is-long-enough-32b")
    assert await sec.authorize_read("anyone", "ch") is True
    assert await sec.authorize_write("anyone", "ch") is True
    assert await sec.authorize_admin("anyone", "ch") is True


@pytest.mark.asyncio
async def test_jwt_authorize_from_token_read():
    sec = JWTChannelSecurity(secret="test-secret-that-is-long-enough-32b")
    token = await sec.generate_token("sys-a", "read", channel_ids=["ch-1"])
    result = await sec.authorize_from_token(token, "ch-1", "read")
    assert result == "sys-a"


@pytest.mark.asyncio
async def test_jwt_authorize_from_token_wrong_channel():
    sec = JWTChannelSecurity(secret="test-secret-that-is-long-enough-32b")
    token = await sec.generate_token("sys-a", "write", channel_ids=["ch-1"])
    result = await sec.authorize_from_token(token, "ch-2", "write")
    assert result is None


@pytest.mark.asyncio
async def test_jwt_authorize_from_token_insufficient_role():
    sec = JWTChannelSecurity(secret="test-secret-that-is-long-enough-32b")
    token = await sec.generate_token("sys-a", "read")
    result = await sec.authorize_from_token(token, "ch-1", "write")
    assert result is None


@pytest.mark.asyncio
async def test_jwt_authorize_from_token_null_channel_scope():
    """channels=None in payload means all channels are allowed."""
    sec = JWTChannelSecurity(secret="test-secret-that-is-long-enough-32b")
    token = await sec.generate_token("sys-a", "admin")  # no channel_ids
    result = await sec.authorize_from_token(token, "any-channel", "admin")
    assert result == "sys-a"


@pytest.mark.asyncio
async def test_jwt_expired_token():
    import jwt as pyjwt

    secret = "test-secret-that-is-long-enough-32b"
    sec = JWTChannelSecurity(secret=secret)
    payload = {"sub": "sys-a", "role": "read", "exp": time.time() - 1}
    token = pyjwt.encode(payload, secret, algorithm="HS256")
    result = await sec.authorize_from_token(token, "ch-1", "read")
    assert result is None
