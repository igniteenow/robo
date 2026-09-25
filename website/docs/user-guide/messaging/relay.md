---
sidebar_position: 30
title: "Robo Relay"
description: "Connect Robo to messaging platforms through a relay connector that owns the platform credentials — enrollment, capabilities, config, and troubleshooting"
---

# Robo Relay (Connector)

:::warning Experimental
Relay is **experimental**. The wire contract, auth scheme, and configuration
may change without a deprecation cycle while the system is being validated.
:::

Robo Relay is not a chat platform itself — it is a **connector system** that
lets your gateway front one or more real messaging platforms (Discord,
Telegram, Slack, WhatsApp, …) **without holding any platform credentials**. A
separate service, the *connector*, owns the platform bot tokens and sockets.
Your gateway dials **out** to the connector over a single authenticated
WebSocket, receives a capability descriptor at handshake, and then exchanges
normalized message events (inbound) and actions (outbound) over that socket.

Key properties:

- **Outbound-only networking.** The gateway never opens an inbound port.
  Inbound messages ride back down the same WebSocket the gateway dialed, so
  relay works behind NAT and on hosts with no public IP.
- **No platform secrets on the gateway.** Bot tokens live on the connector.
  Auth-gated platform media URLs are re-hosted connector-side, so platform
  credentials never cross the wire.
- **Platform-agnostic.** The gateway learns what the fronted platform can do
  (message length limits, markdown dialect, edit/thread/streaming support, and
  the exact set of supported operations) from the handshake descriptor, not
  from hardcoded platform logic.

The formal gateway ⇄ connector interface lives in the repository at
`docs/relay-connector-contract.md`.

## When to use Relay

Relay is for deployments where a hosted or shared connector service manages
the platform side — for example multi-tenant hosting where one shared bot
fronts many users' agents, or setups where you don't want bot tokens on the
gateway machine. If you run your own bots directly, use the native platform
adapters ([Telegram](/user-guide/messaging/telegram),
[Discord](/user-guide/messaging/discord), etc.) instead.

## Credentials

A self-hosted gateway authenticates to the connector with a per-gateway
secret. There are two ways to get one:

- **Managed self-provisioning.** When `gateway.relay_url` (or
  `GATEWAY_RELAY_URL`) is set, no secret is pinned, and the gateway can obtain
  an identity token from your own IdP (`gateway.idp.token_url` /
  `GATEWAY_RELAY_IDP_TOKEN_URL`, OAuth2 client-credentials), it provisions
  itself against the connector's `/relay/provision` endpoint at boot. The
  credentials live only in process memory and are refreshed on every start.
- **Operator-issued credentials.** The connector operator issues the
  per-gateway secret and delivery key for your tenant; put them in the active
  profile's `.env`:

  ```bash
  GATEWAY_RELAY_URL=wss://connector.example.com/relay
  GATEWAY_RELAY_ID=gw-my-box
  GATEWAY_RELAY_SECRET=<per-gateway secret>
  GATEWAY_RELAY_DELIVERY_KEY=<per-tenant delivery key>
  # optional: a reachable URL the connector pokes to wake an idle gateway
  GATEWAY_RELAY_WAKE_URL=https://my-box.example.com/wake
  ```

  Restart the gateway afterwards to pick up the new environment. A pinned
  `GATEWAY_RELAY_SECRET` is always respected: self-provisioning skips when one
  is present.

:::note
There is no `robo gateway enroll` command in this build. Earlier drafts of
these docs described one that redeemed a single-use enrollment token; that
flow was never shipped, and the connector contract for it is not part of this
repository. Use one of the two paths above.
:::

## Configuration

Relay activates when a connector relay URL is configured — there is no
separate feature flag. Deployments that don't set it are unaffected.

| Setting | Where | Meaning |
|---------|-------|---------|
| `GATEWAY_RELAY_URL` | env (`~/.robo/.env`) | Connector relay WebSocket URL. Presence enables the relay platform. |
| `gateway.relay_url` | `config.yaml` | Same as above, config-file form (env takes precedence). |
| `GATEWAY_RELAY_ID` | env | This gateway instance's id (written by `enroll`). |
| `GATEWAY_RELAY_SECRET` | env | Per-gateway secret authenticating the WebSocket upgrade (written by `enroll`). |
| `GATEWAY_RELAY_DELIVERY_KEY` | env | Per-tenant delivery key (written by `enroll`; retained for forward-compat). |
| `GATEWAY_RELAY_WAKE_URL` / `gateway.relay_wake_url` | env / `config.yaml` | Optional wake-poke target for idle/suspended gateways. |
| `GATEWAY_RELAY_PLATFORMS` | env | Comma-separated list of platforms this gateway fronts over one connection (e.g. `discord,telegram`). Usually stamped by the deployment/orchestrator. |
| `GATEWAY_RELAY_BOT_IDS` | env | JSON map of per-platform bot identities, e.g. `{"discord": {"botId": "…"}}`. Paired with `GATEWAY_RELAY_PLATFORMS`. |
| `gateway.idp.token_url` | `config.yaml` | Enrollment/provisioning authenticates via generic OAuth2 client-credentials against your own IdP. |

## Supported capabilities

What actually works over a relay connection is negotiated at handshake: the
connector advertises a `supported_ops` list, and the gateway only uses an
operation the connector explicitly advertises (older connectors fall back to a
legacy `send`/`edit`/`typing`/`follow_up` set). Per-platform capability flags
(edit-based streaming, threads, draft streaming, markdown dialect, message
length limit) also come from the handshake descriptor. Subject to that
negotiation, the relay supports:

- **Text messages and streaming** — sends, replies, and progressive
  edit-based streaming when the fronted platform supports message editing;
  otherwise output degrades to one message per segment.
- **Media, both directions** — outbound images, voice, audio, video, and
  documents are uploaded to the connector (or referenced by public URL) and
  delivered through each platform's native upload lane, with captions.
  Inbound attachments are localized to files for the agent; auth-gated
  platform URLs are re-hosted connector-side so platform credentials never
  reach the gateway. Media re-hosts are capped at 25 MB and expire (~1 hour).
- **Native interactive prompts** — exec approvals, confirmations, and clarify
  questions render with **native platform controls** (Discord buttons,
  Telegram inline keyboards, Slack Block Kit actions, WhatsApp button/list
  messages) instead of numbered-text fallbacks. Button presses come back as
  authenticated prompt responses from the actual clicking user, so the
  gateway's authorization gates apply exactly as to a typed reply. Prompt
  expiry is enforced gateway-side.
- **Reaction ack lifecycle** — the bot's processing-status reactions
  (👀 while working, ✅/❌ on completion) work over the relay. Reactions are
  best-effort: a failed reaction never fails a turn.
- **Thread lifecycle** — creating handoff threads and renaming threads
  (including LLM-titled semantic renames) through platform-abstract
  `thread_create` / `thread_rename` operations, with a no-clobber guard so a
  human's manual rename wins. Availability depends on the platform (e.g.
  Slack threads can't be renamed; WhatsApp has no threads).
- **Typing indicators** — the gateway egresses typing (and stop-typing) through
  the connector while processing.
- **Chat metadata** — `get_chat_info` lookups are proxied to the connector
  when advertised.
- **Buffered delivery and wake** — when the gateway goes idle or disconnects,
  the connector buffers inbound messages durably and replays them in order on
  reconnect (ack-gated, no loss or duplication). If a wake URL is registered,
  the connector pokes it when buffered work arrives for a sleeping gateway.

Multi-platform fronting is supported: one gateway can front several platforms
(e.g. Discord *and* Telegram) over a single relay connection, with each
outbound message tagged for the platform it targets.

## Troubleshooting

**Enrollment fails with 401** — the connector could not verify your identity
token. Re-check your IdP credentials (`gateway.idp.*`) and retry.

**Enrollment fails with 403** — the enrollment token is invalid, expired,
already used, or belongs to a different tenant. Enrollment tokens are
single-use; request a fresh one from whoever provisioned your tenant route.

**"Could not reach the connector"** — check the connector URL. You can paste
either the `wss://…/relay` dial URL or the `https://…` base URL; the CLI maps
between them automatically.

**`enroll` refuses to run** — you are in a managed/hosted install, where the
relay secret is provisioned by the hosting platform. Self-enrollment is only
for self-hosted gateways.

**Relay platform shows as disabled after it previously worked** — a WebSocket
close with code 4401 *after* a successful handshake means the gateway's secret
was revoked (e.g. the instance was deprovisioned). The gateway deliberately
stops reconnecting and reports relay as disabled rather than retrying. A 4401
*before* any successful handshake is treated as a transient
not-yet-provisioned race and retried normally.

**Nothing changed after enrolling** — the gateway reads `GATEWAY_RELAY_*` at
startup. Restart it (`robo gateway restart`).

**A feature (buttons, media, threads…) silently degrades to plain text** — the
connector for your platform did not advertise that operation in its handshake
`supported_ops`. The gateway intentionally falls back to the text behavior
rather than sending an op the connector can't handle.
