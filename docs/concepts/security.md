# Security

Every channel read and write passes through a `ChannelSecurity` instance. Security is pluggable: swap implementations without touching any other code.

---

## The `ChannelSecurity` interface

```python
class ChannelSecurity(abc.ABC):
    async def authenticate(self, token: str) -> str | None:
        """Verify a token. Return the system_id, or None if invalid."""

    async def authorize_read(self, system_id: str, channel_id: str) -> bool:
        """True if system_id may read from channel_id."""

    async def authorize_write(self, system_id: str, channel_id: str) -> bool:
        """True if system_id may write to channel_id."""

    async def authorize_admin(self, system_id: str, channel_id: str) -> bool:
        """True if system_id has admin access to channel_id."""

    async def generate_token(
        self,
        system_id: str,
        role: str,                       # "read" | "write" | "admin"
        channel_ids: list[str] | None,   # None = all channels
        expires_in: float,               # seconds
    ) -> str:
        """Generate a credential token."""
```

A `PermissionError` is raised automatically by `read()`, `write()`, and `subscribe()` when the corresponding `authorize_*` method returns `False`.

---

## OpenSecurity

**For local development only.** No authentication, no authorization — all requests are allowed.

```python
from sssn.core.security import OpenSecurity

channel = PassthroughChannel(
    id="dev-channel",
    name="Dev Channel",
    security=OpenSecurity(),  # or omit — OpenSecurity is the default
)
```

The token **is** the `system_id` — `authenticate("sys-a")` returns `"sys-a"`.

!!! danger "Never use in production"
    `OpenSecurity` grants every caller full access. Use it only in local tests and development environments.

---

## ACLSecurity

Set-based access control. Assign roles with `grant()`, remove with `revoke()`.

```python
from sssn.core.security import ACLSecurity

sec = ACLSecurity()
sec.grant("sensor-1", "write")   # write implies read
sec.grant("dashboard", "read")
sec.grant("admin-tool", "admin") # admin implies read + write

channel = BroadcastChannel(
    id="readings",
    name="Sensor Readings",
    security=sec,
)
```

### Role hierarchy

| Role | `authorize_read` | `authorize_write` | `authorize_admin` |
|------|:---:|:---:|:---:|
| `read` | ✓ | — | — |
| `write` | ✓ | ✓ | — |
| `admin` | ✓ | ✓ | ✓ |

### Constructor shorthand

```python
sec = ACLSecurity(
    read=["dashboard", "monitor"],
    write=["sensor-1", "sensor-2"],
    admin=["ops-tool"],
)
```

### `generate_token()` side effect

Calling `generate_token(system_id, role)` on an `ACLSecurity` instance **also calls `grant(system_id, role)`** and returns the `system_id` as the token. This lets you use the same `generate_token` API across all security implementations.

---

## JWTChannelSecurity

Cryptographically signed tokens with optional per-channel scoping and expiry. Designed for production deployments where channels are exposed over HTTP.

```python
from sssn.core.security import JWTChannelSecurity

sec = JWTChannelSecurity(secret="your-secret-key", algorithm="HS256")
channel = BroadcastChannel(id="public-feed", name="Feed", security=sec)
```

### Generating tokens

```python
# Read-only token, scoped to specific channels, expires in 1 hour
token = await sec.generate_token(
    system_id="dashboard",
    role="read",
    channel_ids=["public-feed", "alerts"],
    expires_in=3600,
)
```

Token payload:
```json
{
    "sub": "dashboard",
    "role": "read",
    "channels": ["public-feed", "alerts"],
    "exp": 1234567890,
    "jti": "a1b2c3d4..."
}
```

### Local vs HTTP authorization

`JWTChannelSecurity` distinguishes two call sites:

**In-process (local):** `authorize_read()`, `authorize_write()`, `authorize_admin()` always return `True`. Local callers are trusted — the system that owns the channel controls access at wiring time.

**HTTP transport:** The `HttpTransport` calls `authorize_from_token(token, channel_id, operation)` before dispatching to the channel. This performs full validation:

1. Decode and verify JWT signature
2. Check expiry (`exp`)
3. Check channel scope (`channels` claim, or `null` = all channels)
4. Check role sufficiency (`read` ≥ `read`, `write` ≥ `read`+`write`, `admin` ≥ all)

Returns the `system_id` on success, `None` on any failure.

---

## Attaching security to a channel

Pass `security` in the constructor:

```python
channel = WorkQueueChannel(
    id="jobs",
    name="Job Queue",
    security=ACLSecurity(write=["scheduler"], read=["worker-1", "worker-2"]),
)
```

Or set it after construction (before `start()`):

```python
channel.security = JWTChannelSecurity(secret=os.environ["CHANNEL_SECRET"])
```

The `security` property is lazy — if you never set it, `OpenSecurity` is used on first access.

---

## Implementing custom security

```python
from sssn.core.security import ChannelSecurity

class OAuthSecurity(ChannelSecurity):
    async def authenticate(self, token: str) -> str | None:
        # Verify with your OAuth provider
        user_info = await oauth_provider.introspect(token)
        return user_info.get("sub") if user_info else None

    async def authorize_read(self, system_id: str, channel_id: str) -> bool:
        return await permissions_service.can_read(system_id, channel_id)

    async def authorize_write(self, system_id: str, channel_id: str) -> bool:
        return await permissions_service.can_write(system_id, channel_id)

    async def authorize_admin(self, system_id: str, channel_id: str) -> bool:
        return await permissions_service.is_admin(system_id, channel_id)

    async def generate_token(self, system_id, role, channel_ids=None, expires_in=86400):
        return await oauth_provider.issue_token(system_id, scopes=[role])
```
