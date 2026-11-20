"""Run tactics over channel events.

A :class:`TacticProcessor` subscribes to a source channel, feeds each event
payload to a tactic, and appends the tactic's output to a sink channel. Output
events point back at their source event through ``parent_ids`` and keep its
``correlation_id``, so a chain of processors stays traceable.

It works with any store that speaks the channel API: a
:class:`~sssn.LocalStore`, a :class:`~sssn.RemoteStore`, or
(with :meth:`TacticProcessor.aprocess`) an :class:`~sssn.AsyncRemoteStore`.
"""

from __future__ import annotations

import inspect
from functools import lru_cache
from typing import Any, Literal

from pydantic import ConfigDict, TypeAdapter

from lllm.protocol import CallContext, Tactic

from .core import Event, Subscription, SubscriptionNotFoundError
from .core.models import json_text, json_value, parse_json


class TacticProcessor:
    """Feed a channel's events through a tactic.

    ``source`` events are read through a named subscription, so a processor
    resumes where it stopped across restarts. ``consumer`` names that
    subscription and defaults to ``"<tactic name>-<source>-processor"``, or
    ``"<tactic name>-<source>-<kind>-processor"`` with a ``kind`` filter, so
    one tactic can process several channels. If those names contain
    whitespace, pass ``consumer`` explicitly.

    Events are processed one at a time and at least once: the tactic runs on
    an event and its output is appended to ``sink`` before the event is
    acknowledged (the subscription cursor moves past it). ``errors`` decides
    what a failure in the tactic or in writing its output does. With
    ``errors="raise"`` the failing event stays unacknowledged and the
    exception propagates, so the next call runs that same event again before
    any event behind it. With ``errors="record"`` the failure is written to
    ``sink`` as a ``kind="error"`` event, the event is acknowledged, and
    processing continues; without a ``sink`` it acts like ``"raise"``. A
    tactic can see an event more than once (after a failure or an interrupted
    run), so it should tolerate repeats, and ``sink`` can then hold more than
    one output for that event.

    Run one worker per ``consumer``; the guarantees above assume it. Workers
    sharing a consumer can process the same event twice, and can lose one:
    when another worker acknowledges the event this processor ran, this
    processor's acknowledgement covers the next pending event instead, which
    it runs right away, even past ``limit``. That event is already
    acknowledged, so with ``errors="raise"`` a failure loses it.
    """

    def __init__(
        self,
        tactic: Tactic[Any, Any],
        store: Any,
        *,
        source: str,
        sink: str | None = None,
        consumer: str | None = None,
        kind: str | None = None,
        output_kind: str = "result",
        errors: Literal["raise", "record"] = "raise",
    ) -> None:
        if errors not in {"raise", "record"}:
            raise ValueError("errors must be 'raise' or 'record'.")
        self.tactic = tactic
        self.store = store
        self.source = source
        self.sink = sink
        self.consumer = consumer or _default_consumer(tactic, source, kind)
        self.output_kind = output_kind
        self.errors = errors
        self.kind = kind
        self.subscription_id = self.consumer
        self._subscribed = False

    def process(self, limit: int | None = None) -> list[Event | Any]:
        """Process pending events; return sink events (or raw outputs without a sink).

        Each event is peeked at the subscription cursor, run through the
        tactic, written to ``sink``, and only then acknowledged. ``limit`` caps
        the number of results, outputs and recorded errors alike. This method
        needs a synchronous store; use :meth:`aprocess` with async stores such
        as :class:`~sssn.AsyncRemoteStore`.
        """

        if _is_async_store(self.store):
            raise TypeError(
                f"process() cannot use the async store {type(self.store).__name__}; "
                "use `await processor.aprocess()` with async stores."
            )
        self._subscribe()
        results: list[Event | Any] = []
        while limit is None or len(results) < limit:
            event = self._peek()
            if event is None:
                break
            results.append(self._call(event))
            acked = self.store.pull_subscription(self.subscription_id, limit=1)
            if not acked:
                break
            if acked[0].id != event.id:
                # Another worker acknowledged ``event`` first, so this pull
                # acknowledged the next event. Run it now: it is already
                # acknowledged, so a raised failure is not retried.
                results.append(self._call(acked[0]))
        return results

    async def aprocess(self, limit: int | None = None) -> list[Event | Any]:
        """Async variant of :meth:`process` using ``tactic.arun``.

        It works with synchronous and asynchronous stores, with the same
        at-least-once semantics.
        """

        await self._asubscribe()
        results: list[Event | Any] = []
        while limit is None or len(results) < limit:
            event = await self._apeek()
            if event is None:
                break
            results.append(await self._acall(event))
            acked = await _maybe_await(
                self.store.pull_subscription(self.subscription_id, limit=1)
            )
            if not acked:
                break
            if acked[0].id != event.id:
                # Another worker acknowledged ``event`` first, so this pull
                # acknowledged the next event. Run it now: it is already
                # acknowledged, so a raised failure is not retried.
                results.append(await self._acall(acked[0]))
        return results

    def _peek(self) -> Event | None:
        subscription = self.store.get_subscription(self.subscription_id)
        events = self.store.query_events(
            subscription.channel,
            after_cursor=subscription.cursor,
            limit=1,
            kind=subscription.filters.get("kind"),
        )
        return events[0] if events else None

    async def _apeek(self) -> Event | None:
        subscription = await _maybe_await(
            self.store.get_subscription(self.subscription_id)
        )
        events = await _maybe_await(
            self.store.query_events(
                subscription.channel,
                after_cursor=subscription.cursor,
                limit=1,
                kind=subscription.filters.get("kind"),
            )
        )
        return events[0] if events else None

    def _call(self, event: Event) -> Event | Any:
        try:
            output = self.tactic.run(event.payload, context=self._context(event))
            sink_event = self._output_event(event, output)
            return output if sink_event is None else self.store.append_event(sink_event)
        except Exception as exc:
            return self.store.append_event(self._error_event(event, exc))

    async def _acall(self, event: Event) -> Event | Any:
        try:
            output = await self.tactic.arun(event.payload, context=self._context(event))
            sink_event = self._output_event(event, output)
            if sink_event is None:
                return output
            return await _maybe_await(self.store.append_event(sink_event))
        except Exception as exc:
            error_event = self._error_event(event, exc)
            return await _maybe_await(self.store.append_event(error_event))

    def _subscribe(self) -> None:
        if self._subscribed:
            return
        try:
            subscription = self.store.get_subscription(self.subscription_id)
        except Exception as exc:
            if not _is_missing(exc):
                raise
            subscription = self.store.create_subscription(
                self.source, **self._subscription_args()
            )
        self._check_subscription(subscription)
        self._subscribed = True

    async def _asubscribe(self) -> None:
        if self._subscribed:
            return
        try:
            subscription = await _maybe_await(
                self.store.get_subscription(self.subscription_id)
            )
        except Exception as exc:
            if not _is_missing(exc):
                raise
            subscription = await _maybe_await(
                self.store.create_subscription(self.source, **self._subscription_args())
            )
        self._check_subscription(subscription)
        self._subscribed = True

    def _check_subscription(self, subscription: Subscription) -> None:
        kind = subscription.filters.get("kind")
        if subscription.channel == self.source and kind == (self.kind or None):
            return
        raise ValueError(
            f"Subscription {self.subscription_id!r} already reads channel "
            f"{subscription.channel!r} with kind filter {kind!r}, but this "
            f"processor reads channel {self.source!r} with kind filter "
            f"{self.kind or None!r}. Pass a distinct consumer= to give this "
            "processor its own subscription."
        )

    def _subscription_args(self) -> dict[str, Any]:
        return {
            "subscription_id": self.subscription_id,
            "consumer": self.consumer,
            "filters": {"kind": self.kind} if self.kind else None,
        }

    def _context(self, event: Event) -> CallContext:
        return CallContext(
            caller=self.consumer,
            tags={"channel": self.source},
            metadata={
                "event_id": event.id,
                "event_kind": event.kind,
                "correlation_id": event.correlation_id or event.id,
            },
        )

    def _output_event(self, event: Event, output: Any) -> Event | None:
        if self.sink is None:
            return None
        return Event(
            channel=self.sink,
            source=self.consumer,
            kind=self.output_kind,
            payload=_payload(output),
            correlation_id=event.correlation_id or event.id,
            parent_ids=(event.id,),
        )

    def _error_event(self, event: Event, exc: Exception) -> Event:
        if self.errors == "raise" or self.sink is None:
            raise exc
        return Event(
            channel=self.sink,
            source=self.consumer,
            kind="error",
            payload={"error": str(exc), "type": type(exc).__name__},
            correlation_id=event.correlation_id or event.id,
            parent_ids=(event.id,),
        )


def _default_consumer(tactic: Tactic[Any, Any], source: str, kind: str | None) -> str:
    # One subscription per tactic, source, and kind filter, so the same tactic
    # can process several channels. A tactic name may hold whitespace, which
    # a subscription id cannot.
    parts = (tactic.tactic_name, source, kind, "processor")
    consumer = "-".join(part for part in parts if part)
    if any(ch.isspace() for ch in consumer):
        raise ValueError(
            f"Cannot use the default consumer {consumer!r} (tactic name, source, "
            "and kind): a consumer name cannot contain whitespace. Pass "
            "consumer= to name this processor's subscription."
        )
    return consumer


def _payload(value: Any) -> Any:
    # The JSON form a store keeps, by the stores' rule: NaN outside a model
    # raises, a model writes its own JSON, and a lone surrogate is kept.
    # Output a store cannot hold raises InvalidPayloadError here, a failure
    # of this event that errors="raise" or "record" handles.
    adapter = _output_adapter(type(value))
    if adapter is not None:
        # The output type's own schema first, as 0.2.0 used it (a model's own
        # serializer, Annotated serializers, a dataclass's config).
        try:
            text = json_text(adapter, [value])
        except Exception:
            # The schema could not write it, as for a value of the wrong
            # type: infer it from the value, as 0.2.0 fell back to.
            pass
        else:
            # NaN outside a model is refused here, with no second try.
            return parse_json(text)[0]
    return json_value(value)


@lru_cache(maxsize=256)
def _output_adapter(output_type: type) -> TypeAdapter[Any] | None:
    """An adapter for a list of ``output_type``, or None if none can be built.

    The list lets the config apply: TypeAdapter refuses ``config=`` for a
    dataclass or a TypedDict itself.
    """

    try:
        adapter = TypeAdapter(
            list[output_type],  # type: ignore[valid-type]
            config=ConfigDict(ser_json_inf_nan="constants"),
        )
    except Exception:
        return None
    # Since Pydantic 2.10, a type with annotations it cannot resolve (a name
    # imported only for type checkers, a local class) still gives an
    # adapter, which fails when it is used.
    if getattr(adapter, "pydantic_complete", True) is False:
        return None
    return adapter


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _is_async_store(store: Any) -> bool:
    return inspect.iscoroutinefunction(getattr(store, "pull_subscription", None))


def _is_missing(exc: Exception) -> bool:
    if isinstance(exc, SubscriptionNotFoundError):
        return True
    return getattr(exc, "status_code", None) == 404
