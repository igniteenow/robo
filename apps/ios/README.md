# Robo for iOS

Native SwiftUI app for Robo (Ignitee Now). Two ways to run, one interface:

**On this iPhone (Local mode).** Enter an API key (OpenAI, OpenRouter, Anthropic,
Groq, xAI, DeepSeek, Mistral, or any OpenAI-compatible endpoint) and Robo runs on
the phone itself — the same agent loop, the same SOUL.md (identity, evidence
discipline, deliberation protocol), the same memory content policy, deep
thinking on by default. Its hands are what an iPhone can genuinely do:
web search and fetch, its own files (visible in the Files app under Robo),
real JavaScript execution in the system engine, memory, reminders and calendar
with your permission. Destructive actions stop for approval. Sessions persist
and compact automatically.

**Via a computer (Gateway mode).** Pair with Robo running on any machine
(`robo serve --pair`) for terminals, code, repos, browsers, Ghidra — the full
toolset. The phone controls it, streams its work and answers approvals.

Why two modes and not one: iOS has no shell, no root and no filesystem outside
the app sandbox. No app on the App Store can run `apt`, Docker or edit
arbitrary files — Claude and ChatGPT's apps don't either; their agents run on
servers. Robo gives you both: everything the phone can do on the phone, and
everything else through your own machine with no cloud relay in between.

## Features
- Local mode: multi-provider streaming with tool calls (OpenAI-compatible +
  Anthropic), on-device tools, approvals, memory, session persistence, context
  compaction. Keys live in the Keychain; requests go straight to the provider.
- Chat with streaming replies; tool activity collapses to one row per turn
  (tap to expand), like the desktop and TUI.
- **Hold-to-talk**: on-device speech recognition → sent as a request; replies
  read aloud with the system voice (toggle in Settings).
- Approvals: Allow once / Allow for this session / Deny (deny stops the turn).
- Sessions: resume any session from the gateway; start new ones.
- Pairing by QR code or pasted string; token stored in the iOS Keychain.
- Reconnects automatically; works over LAN, Tailscale/VPN, or HTTPS.

## Build (Mac with Xcode 16+)
```bash
brew install xcodegen
cd apps/ios
xcodegen generate            # creates Robo.xcodeproj from project.yml
open Robo.xcodeproj          # set your Team in Signing & Capabilities
xcodebuild -scheme Robo -destination 'platform=iOS Simulator,name=iPhone 16' test
```

## Pair with your gateway
On the machine running Robo:
```bash
robo serve --host 0.0.0.0 --port 8642 --pair
```
`--pair` prints a QR code and the string `robo://pair?url=<gateway-url>&token=<token>`.
Scan it in the app (or paste it). For access outside your LAN put the gateway
behind HTTPS (Caddy/nginx) or a Tailscale address — the app refuses cleartext to
non-local hosts (App Transport Security).

## App Store checklist
- Bundle id `com.igniteenow.robo`, Team ID in `project.yml`, version/build bump.
- `PrivacyInfo.xcprivacy` is included (no tracking, no collected data,
  UserDefaults reason CA92.1). Privacy strings for microphone, speech
  recognition, camera, local network, reminders and calendar are in the
  Info.plist section of `project.yml` — App Review reads them verbatim.
  The reminders and calendar strings are mandatory: the local tools call
  EventKit's full-access APIs, and iOS terminates an app that requests
  access without them.
- The brand typeface (Poppins, SIL Open Font License 1.1) ships in
  `Robo/Resources/Fonts` with its licence text and is registered at launch by
  `RoboTheme.registerFonts()`, so no `UIAppFonts` plist entry is needed. The
  OFL permits embedding in a commercial app; keep `OFL.txt` in the bundle.
- `UIFileSharingEnabled` and `LSSupportsOpeningDocumentsInPlace` are set so
  Robo's working files appear in the Files app under "On My iPhone > Robo".
- `UIBackgroundModes: [audio]` lets a spoken reply finish if the screen locks.
  Say so in the App Review notes; reviewers reject unexplained background audio.
- App Review notes: explain that the app connects to the user's **own** Robo
  gateway (provide a demo gateway URL + token in the review notes, or the
  reviewer cannot get past pairing).
- Export compliance: `ITSAppUsesNonExemptEncryption = false` (TLS only).
- Screenshots: pairing, chat with a collapsed tool run, approval sheet, voice.
- Distribute via TestFlight first; the reconnect and speech paths need real
  devices (the Simulator has no microphone by default).

## Protocol (so the client cannot drift from the gateway)
JSON-RPC 2.0 over `wss://<gateway>/api/ws`. Methods used: `session.create`,
`session.list`, `session.resume`, `session.interrupt`, `prompt.submit`,
`approval.respond`. Events consumed: `message.start|delta|complete`,
`reasoning.delta`, `tool.start|complete`, `status.update`, `approval.request`,
`message.user`, `session.info`. The Python test
`tests/tui_gateway/test_ios_client_contract.py` asserts these methods exist on
the gateway; `RoboTests/RPCFramesTests.swift` asserts the frame shapes on the
client.
