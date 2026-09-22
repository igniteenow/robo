# Analysis Record

Robo populates this record automatically from the assigned task. It is an audit artifact, not
a prerequisite or signature gate — matching the convention used by the `web-pentest` skill's
`authorization.md`. Save it as `investigation/authorization.md`.

---

**Investigation ID:** <UUID or short slug>
**Operator:** <name of the person driving this Robo session>
**Date opened:** <ISO 8601 timestamp>

## Target

- **File:** <path>
- **SHA-256:** <hash>
- **Format/Arch:** <e.g. PE32+, ARM64>
- **Provenance:** <where this binary came from — your own build, an open-source release, a
  vendor deliverable, a CTF challenge, a sample from an authorized malware repository, etc.>

## Authorization Basis

- Operator request: <copy or summarize the task that named this target>
- Why analysis of this specific binary is authorized: <you own it / it's open source / it was
  explicitly provided for this purpose / other — be specific, don't leave this generic>

## Isolation (required if any dynamic analysis is planned)

- Environment: <container / VM / sandboxed execute_code — name it>
- Network egress: <disabled / restricted to: ... / not applicable (static analysis only)>
- Cleanup plan: <how the environment gets torn down after analysis>

## Runtime Decisions

Append consequential-action decisions here automatically (matches the approval-prompt
history from `tools/approval.py`):

- <timestamp> — <action summary> — <allow once / session / deny>
