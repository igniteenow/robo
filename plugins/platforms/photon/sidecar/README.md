# Photon sidecar

Small Node helper that bridges Robo Agent to Photon's Spectrum SDK
(`spectrum-ts`).  Robo is Python; Photon has no public HTTP
send-message endpoint today; replies therefore go through this sidecar.

The sidecar:

- runs `Spectrum({ projectId, projectSecret, providers: [imessage.config()] })`
- exposes a loopback-only HTTP control channel for the Python adapter
  to push send/typing requests (auth via `X-Robo-Sidecar-Token`)
- drains the inbound message stream so `spectrum-ts` keeps its
  reconnect/heartbeat machinery alive and Robo can receive inbound messages
  over the adapter's loopback `GET /inbound` stream

## Install

```bash
cd plugins/platforms/photon/sidecar
npm install
```

The Robo plugin's `robo photon setup` command runs `npm install`
here automatically.

## Run standalone

For debugging:

```bash
PHOTON_PROJECT_ID=... PHOTON_PROJECT_SECRET=... \
PHOTON_SIDECAR_PORT=8789 PHOTON_SIDECAR_TOKEN=$(openssl rand -hex 16) \
node index.mjs
```

In normal use, the Python adapter supervises this process — start,
restart on crash, kill on shutdown — and never asks the user to run
it by hand.

## Why a sidecar at all?

Photon's Spectrum send path is exposed through the TypeScript SDK's
`Space.send(...)` API. Robo is Python, so replies go through this sidecar
until Photon ships a public HTTP send endpoint.

When Photon ships an HTTP send endpoint, the plan is to retire this
sidecar entirely and call it directly from Python.  The plugin's
outbound code path is already isolated behind small helpers
(`_sidecar_send`, `_sidecar_send_richlink`, and `_sidecar_send_attachment` in
`adapter.py`) to make that swap localized.
