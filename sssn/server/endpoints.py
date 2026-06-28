"""Custom endpoint metadata for SSSN services."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
EndpointScope = Literal["store", "channel", "subscription", "artifact", "snapshot"]
F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class StoreEndpointSpec:
    method: HttpMethod
    path: str
    name: str
    scope: EndpointScope = "store"
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


class endpoint:
    """Decorator namespace for custom SSSN store/channel endpoints."""

    @staticmethod
    def get(
        path: str,
        *,
        name: str | None = None,
        scope: EndpointScope = "store",
        description: str = "",
        tags: Sequence[str] = (),
    ) -> Callable[[F], F]:
        return _attach(
            "GET",
            path,
            name=name,
            scope=scope,
            description=description,
            tags=tags,
        )

    @staticmethod
    def post(
        path: str,
        *,
        name: str | None = None,
        scope: EndpointScope = "store",
        description: str = "",
        tags: Sequence[str] = (),
    ) -> Callable[[F], F]:
        return _attach(
            "POST",
            path,
            name=name,
            scope=scope,
            description=description,
            tags=tags,
        )

    @staticmethod
    def put(
        path: str,
        *,
        name: str | None = None,
        scope: EndpointScope = "store",
        description: str = "",
        tags: Sequence[str] = (),
    ) -> Callable[[F], F]:
        return _attach(
            "PUT",
            path,
            name=name,
            scope=scope,
            description=description,
            tags=tags,
        )

    @staticmethod
    def patch(
        path: str,
        *,
        name: str | None = None,
        scope: EndpointScope = "store",
        description: str = "",
        tags: Sequence[str] = (),
    ) -> Callable[[F], F]:
        return _attach(
            "PATCH",
            path,
            name=name,
            scope=scope,
            description=description,
            tags=tags,
        )

    @staticmethod
    def delete(
        path: str,
        *,
        name: str | None = None,
        scope: EndpointScope = "store",
        description: str = "",
        tags: Sequence[str] = (),
    ) -> Callable[[F], F]:
        return _attach(
            "DELETE",
            path,
            name=name,
            scope=scope,
            description=description,
            tags=tags,
        )


def endpoint_spec(fn: Callable[..., Any]) -> StoreEndpointSpec | None:
    spec = getattr(fn, "__sssn_endpoint__", None)
    return spec if isinstance(spec, StoreEndpointSpec) else None


def _attach(
    method: HttpMethod,
    path: str,
    *,
    name: str | None,
    scope: EndpointScope,
    description: str,
    tags: Sequence[str],
) -> Callable[[F], F]:
    normalized = path if path.startswith("/") else f"/{path}"

    def decorator(fn: F) -> F:
        setattr(
            fn,
            "__sssn_endpoint__",
            StoreEndpointSpec(
                method=method,
                path=normalized,
                name=name or fn.__name__,
                scope=scope,
                description=description or (fn.__doc__ or "").strip(),
                tags=tuple(tags),
            ),
        )
        return fn

    return decorator
