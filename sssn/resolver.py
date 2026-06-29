"""Local SSSN ref resolution."""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .client import AsyncSSSNClient, SSSNClient
from .core import SSSNError
from .stores import LocalStore

_SSSN_CONFIG_REF_SECTIONS = {"channels", "snapshots"}
_NON_SSSN_CONFIG_REF_SECTIONS = {
    "assets",
    "configs",
    "docs",
    "examples",
    "runs",
    "schemas",
    "services",
    "tactics",
}


class SSSNRefError(SSSNError, ValueError):
    """Raised when an SSSN `psi://` ref or binding is invalid."""


@dataclass(frozen=True)
class SSSNRef:
    """A stable `psi://org/package/channels/name` or snapshots ref."""

    value: str
    org: str = field(init=False)
    package: str = field(init=False)
    resource_kind: str = field(init=False)
    name: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise SSSNRefError("SSSN ref must be a non-empty string.")
        parsed = urlparse(self.value)
        if parsed.scheme != "psi":
            raise SSSNRefError(f"SSSN ref must use psi:// scheme: {self.value}")
        if parsed.params or parsed.query or parsed.fragment:
            raise SSSNRefError(
                "SSSN ref must not include params, query, or fragment: "
                f"{self.value}"
            )
        org = parsed.netloc
        raw_parts = parsed.path.split("/")
        if (
            len(raw_parts) != 4
            or raw_parts[0] != ""
            or any(not part for part in raw_parts[1:])
        ):
            raise SSSNRefError(
                "SSSN ref must have shape "
                "psi://org/package/channels/name or "
                f"psi://org/package/snapshots/name: {self.value}"
            )
        package, resource_kind, name = raw_parts[1:]
        if not org or not package.strip() or not name.strip():
            raise SSSNRefError(f"SSSN ref contains an empty segment: {self.value}")
        for segment in (org, package, resource_kind, name):
            decoded_segment = unquote(segment)
            if any(ch.isspace() for ch in decoded_segment):
                raise SSSNRefError(
                    "SSSN ref contains a whitespace-bearing segment: "
                    f"{self.value}"
                )
        for segment in (org, package, name):
            decoded_segment = unquote(segment)
            if (
                decoded_segment in {".", ".."}
                or any(ch in decoded_segment for ch in "/:\\")
                or "%" in segment
            ):
                raise SSSNRefError(
                    f"SSSN ref contains an invalid segment: {self.value}"
                )
        if resource_kind not in _SSSN_CONFIG_REF_SECTIONS:
            raise SSSNRefError(
                "SSSN ref must point at /channels/ or /snapshots/, "
                f"got /{resource_kind}/: {self.value}"
            )
        object.__setattr__(self, "org", org)
        object.__setattr__(self, "package", package)
        object.__setattr__(self, "resource_kind", resource_kind)
        object.__setattr__(self, "name", name)

    @classmethod
    def parse(cls, value: str | "SSSNRef") -> "SSSNRef":
        if isinstance(value, cls):
            return value
        return cls(value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ResolvedSSSNRef:
    """A concrete local binding for an SSSN ref."""

    ref: str
    resource_kind: str
    name: str
    url: str | None = None
    store: str | None = None
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SSSNResolver:
    """Resolve SSSN refs to local stores or HTTP clients."""

    def __init__(self, *, root: str | Path = ".") -> None:
        self.root = Path(_path_value(root, "config root")).expanduser().resolve()
        self._bindings: dict[str, ResolvedSSSNRef] = {}
        self._stores: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_config(cls, path: str | Path) -> "SSSNResolver":
        root, target = _config_target(path)
        resolver = cls(root=root)
        config = _load_toml(target)
        refs = config.get("refs", {})
        if not isinstance(refs, dict):
            raise SSSNRefError("[refs] must be a TOML table.")
        resolver._stores = _table_of_tables(config.get("stores", {}), "stores")
        for raw_ref, data in refs.items():
            if not _is_sssn_config_ref(raw_ref):
                continue
            if not isinstance(data, dict):
                raise SSSNRefError(f"Ref binding must be a table: {raw_ref}")
            resolver.bind(
                raw_ref,
                url=data.get("url"),
                store=data.get("store"),
                path=data.get("path"),
                metadata={
                    key: value
                    for key, value in data.items()
                    if key not in {"url", "store", "path"}
                },
            )
        return resolver

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        root: str | Path | None = None,
    ) -> "SSSNResolver":
        root_value = "." if root is None else root
        root_path = Path(_path_value(root_value, "config root"))
        target = root_path / ".psi" / "config.toml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return cls.from_config(root_path)

    def bind(
        self,
        ref: str | SSSNRef,
        *,
        url: str | None = None,
        store: str | None = None,
        path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        parsed = SSSNRef.parse(ref)
        if metadata is not None and not isinstance(metadata, dict):
            raise SSSNRefError(f"Ref binding metadata must be a table: {parsed}")
        url = _normalize_text_target(parsed.value, "url", url)
        store = _normalize_text_target(parsed.value, "store", store)
        path = _normalize_text_target(parsed.value, "path", path)
        _validate_target(parsed.value, url=url, store=store, path=path)
        self._bindings[parsed.value] = ResolvedSSSNRef(
            ref=parsed.value,
            resource_kind=parsed.resource_kind,
            name=parsed.name,
            url=url,
            store=store,
            path=path,
            metadata=deepcopy(metadata or {}),
        )

    def resolve(self, ref: str | SSSNRef) -> ResolvedSSSNRef:
        parsed = SSSNRef.parse(ref)
        try:
            binding = self._bindings[parsed.value]
        except KeyError as exc:
            raise SSSNRefError(f"SSSN ref is not bound: {parsed}") from exc
        return _copy_binding(binding)

    def refs(self) -> tuple[str, ...]:
        return tuple(sorted(self._bindings))

    def client(
        self,
        ref: str | SSSNRef,
        *,
        timeout: float | None = 30.0,
        transport: Any = None,
    ) -> SSSNClient:
        binding = self.resolve(ref)
        if binding.url is None:
            raise SSSNRefError(f"SSSN ref is not bound to an HTTP URL: {binding.ref}")
        return SSSNClient(binding.url, timeout=timeout, transport=transport)

    def async_client(
        self,
        ref: str | SSSNRef,
        *,
        timeout: float | None = 30.0,
        transport: Any = None,
    ) -> AsyncSSSNClient:
        binding = self.resolve(ref)
        if binding.url is None:
            raise SSSNRefError(f"SSSN ref is not bound to an HTTP URL: {binding.ref}")
        return AsyncSSSNClient(binding.url, timeout=timeout, transport=transport)

    def store_path(self, ref: str | SSSNRef) -> Path:
        binding = self.resolve(ref)
        target = binding.store if binding.store is not None else binding.path
        if target is None:
            raise SSSNRefError(f"SSSN ref is not bound to a local store: {binding.ref}")
        return _resolve_under_root(self.root, target)

    def local_store(self, ref: str | SSSNRef) -> LocalStore:
        return LocalStore(self.store_path(ref))

    def stores(self) -> dict[str, dict[str, Any]]:
        return deepcopy(self._stores)

    def store(self, name: str) -> dict[str, Any]:
        _validate_table_name(name, f"stores.{name}")
        try:
            return deepcopy(self._stores[name])
        except KeyError as exc:
            raise KeyError(f"Store config is not bound: {name}") from exc


def _copy_binding(binding: ResolvedSSSNRef) -> ResolvedSSSNRef:
    return ResolvedSSSNRef(
        ref=binding.ref,
        resource_kind=binding.resource_kind,
        name=binding.name,
        url=binding.url,
        store=binding.store,
        path=binding.path,
        metadata=deepcopy(binding.metadata),
    )


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python 3.10 fallback
        import tomli as tomllib  # type: ignore[no-redef]
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _config_target(path: str | Path) -> tuple[Path, Path]:
    target = Path(_path_value(path, "config path")).expanduser()
    if target.is_dir():
        root = target
        target = target / ".psi" / "config.toml"
    else:
        root = target.parent.parent if target.parent.name == ".psi" else target.parent
    return root.resolve(), target


def _is_sssn_config_ref(ref: Any) -> bool:
    if not isinstance(ref, str) or not ref.strip():
        raise SSSNRefError("Ref binding key must be a non-empty string.")
    parsed = urlparse(ref)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) == 3 and parts[1] in _NON_SSSN_CONFIG_REF_SECTIONS:
        return False
    return True


def _table_of_tables(value: Any, name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise SSSNRefError(f"[{name}] must be a TOML table.")
    result: dict[str, dict[str, Any]] = {}
    for key, item in value.items():
        if not isinstance(item, dict):
            raise SSSNRefError(f"[{name}.{key}] must be a TOML table.")
        if not isinstance(key, str):
            raise SSSNRefError(
                f"[{name}.{key}] must use a non-empty path-segment name."
            )
        _validate_table_name(key, f"{name}.{key}")
        item_copy = deepcopy(item)
        _validate_store_table_values(key, item_copy)
        result[key] = item_copy
    return result


def _validate_table_name(value: Any, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "%" in value
        or any(ch.isspace() for ch in value)
        or any(ch in value for ch in "/:\\")
    ):
        raise SSSNRefError(f"[{label}] must use a non-empty path-segment name.")


def _validate_store_table_values(key: str, item: dict[str, Any]) -> None:
    if "path" not in item:
        return
    path = item["path"]
    if (
        not isinstance(path, str)
        or not path
        or path != path.strip()
        or any(ch.isspace() for ch in path)
    ):
        raise SSSNRefError(
            f"[stores.{key}] path must be a non-empty string without whitespace."
        )


def _normalize_text_target(ref: str, name: str, value: Any) -> str | None:
    if value is None:
        return None
    if (
        isinstance(value, str)
        and value
        and value == value.strip()
        and not any(ch.isspace() for ch in value)
    ):
        return value
    raise SSSNRefError(
        f"Ref binding target {name!r} must be a non-empty string without whitespace: {ref}"
    )


def _validate_target(
    ref: str,
    *,
    url: str | None,
    store: str | None,
    path: str | None,
) -> None:
    targets = {"url": url, "store": store, "path": path}
    active = [name for name, value in targets.items() if value is not None]
    if not active:
        raise SSSNRefError(f"Ref binding must declare one concrete target: {ref}")
    if len(active) > 1:
        targets_text = ", ".join(active)
        raise SSSNRefError(
            "Ref binding must declare only one concrete target, "
            f"got {targets_text}: {ref}"
        )
    if url is not None:
        _validate_url_target(ref, url)


def _validate_url_target(ref: str, value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme in {"http", "https"}
        and parsed.netloc
        and not any(ch.isspace() for ch in value)
    ):
        return
    raise SSSNRefError(
        f"Ref binding target 'url' must be an absolute HTTP(S) URL: {ref}"
    )


def _resolve_under_root(root: Path, path: str) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = root / target
    return target.resolve()


def _path_value(value: Any, label: str) -> str:
    try:
        text = os.fspath(value)
    except TypeError as exc:
        raise ValueError(f"{label} must be a non-empty path string") from exc
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{label} must be a non-empty path string")
    return text.strip()
