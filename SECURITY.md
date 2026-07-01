# Security Policy

SSSN stores semantic events, artifacts, snapshots, subscriptions, and channel
metadata. Treat stores, HTTP clients/servers, artifact payloads, and package
metadata as security-sensitive surfaces.

## Supported Versions

The active `main` branch receives security fixes.

## Reporting A Vulnerability

Please report suspected vulnerabilities privately to the project maintainers.
Do not open a public issue with exploit details.

Include:

- affected version or commit
- store, server, client, or package helper involved
- reproduction steps
- expected and actual behavior
- whether the issue involves event validation, artifact storage, snapshots,
  subscriptions, custom endpoints, or local filesystem paths

## Scope

Security-sensitive areas include:

- local store path handling
- event, artifact, and snapshot payload validation
- HTTP server/client request handling
- custom channel endpoint mounting
- package metadata exported for PsiHub cards and config templates
