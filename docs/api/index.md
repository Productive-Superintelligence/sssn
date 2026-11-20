# Python API

Everything here is importable from `sssn`, as in `from sssn import LocalStore`. The guide pages explain how the pieces fit; come here for exact parameters and defaults.

## Channels and records

::: sssn.core.models.Channel

::: typing.Literal

::: sssn.core.models.Event

::: sssn.core.models.Artifact

::: sssn.core.models.Snapshot

::: sssn.core.models.Subscription

## Stores

::: sssn.stores.local.LocalStore

## Serving a store

::: sssn.server.fastapi.create_app

::: sssn.server.endpoints.endpoint

::: sssn.server.endpoints.StoreEndpointSpec

::: typing.Literal

## Remote stores

::: sssn.client.http.RemoteStore

::: sssn.client.http.AsyncRemoteStore

::: sssn.client.http.RemoteStoreError

## Processing

::: sssn.processing.TacticProcessor

## Packages and refs

::: sssn.resources.channel_resource

::: sssn.resources.snapshot_resource

::: sssn.resolver.ChannelRef

::: sssn.resolver.ChannelResolver

::: sssn.resolver.ResolvedChannelRef

::: sssn.resolver.ChannelRefError

## Errors

::: sssn.core.errors.NetworkError

::: sssn.core.errors.ChannelExistsError

::: sssn.core.errors.ChannelNotFoundError

::: sssn.core.errors.EventExistsError

::: sssn.core.errors.EventNotFoundError

::: sssn.core.errors.ArtifactNotFoundError

::: sssn.core.errors.SnapshotNotFoundError

::: sssn.core.errors.SubscriptionExistsError

::: sssn.core.errors.SubscriptionNotFoundError

::: sssn.core.errors.InvalidPayloadError

::: sssn.core.errors.StoreBusyError
