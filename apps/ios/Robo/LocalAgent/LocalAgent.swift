// LocalAgent.swift — Robo iOS · Local mode
// The same agent loop Robo runs on a Mac or Kali box, on the phone: build the
// system prompt from the bundled SOUL.md (identity, evidence discipline,
// deliberation protocol) plus the user's MEMORY.md / USER.md, call the model
// with the on-device toolset, execute tool calls (stopping for approval on
// destructive ones), feed results back, repeat until the model answers.
// It emits the same GatewayEvent stream as the remote gateway, so the UI is
// identical in both modes.

import Foundation
import UIKit

public struct LocalSession: Codable, Identifiable {
    public var id: String
    public var title: String
    public var created: Date
    public var messages: [ChatMessage]
}

@MainActor
public final class LocalAgent {
    public var onEvent: (@MainActor (GatewayEvent) -> Void)?
    public var approvalHandler: (@MainActor (ApprovalRequest) async -> String)?   // returns once|session|deny

    public private(set) var session: LocalSession
    private var config: ProviderConfig
    private var task: Task<Void, Never>?
    private var sessionApproved: Set<String> = []
    private var interrupted = false
    private var totalInput = 0
    private var totalOutput = 0

    private static let maxIterations = 60
    private static let compactAtChars = 280_000      // ~70k tokens of transcript before compaction

    public init(config: ProviderConfig, session: LocalSession? = nil) {
        self.config = config
        self.session = session ?? LocalSession(id: UUID().uuidString, title: "New session", created: Date(), messages: [])
    }

    public func update(config: ProviderConfig) { self.config = config }

    // MARK: - Persistence (Documents/sessions/<id>.json)

    private static var sessionsDir: URL {
        let d = LocalToolbox.documents.appendingPathComponent("sessions")
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }

    public static func listSessions() -> [LocalSession] {
        let files = (try? FileManager.default.contentsOfDirectory(at: sessionsDir, includingPropertiesForKeys: nil)) ?? []
        return files.compactMap { try? JSONDecoder().decode(LocalSession.self, from: Data(contentsOf: $0)) }.sorted { $0.created > $1.created }
    }

    public static func load(_ id: String) -> LocalSession? {
        try? JSONDecoder().decode(LocalSession.self, from: Data(contentsOf: sessionsDir.appendingPathComponent("\(id).json")))
    }

    private func persist() {
        if let d = try? JSONEncoder().encode(session) {
            try? d.write(to: Self.sessionsDir.appendingPathComponent("\(session.id).json"), options: .atomic)
        }
    }

    // MARK: - Prompt

    private func systemPrompt() -> String {
        var parts: [String] = []
        if let url = Bundle.main.url(forResource: "SOUL", withExtension: "md") ?? Bundle.main.url(forResource: "SOUL", withExtension: "md", subdirectory: "Resources"), let soul = try? String(contentsOf: url, encoding: .utf8) {
            parts.append(soul)
        } else {
            parts.append("You are Robo, an autonomous engineering agent by Ignitee Now. Think before acting; verify before asserting; correct yourself when evidence disagrees.")
        }
        let f = DateFormatter(); f.dateStyle = .full; f.timeStyle = .short
        parts.append("""
        # Runtime
        You are running ON THE USER'S IPHONE in Local mode (no gateway). Date: \(f.string(from: Date())) (\(TimeZone.current.identifier)). Device: \(UIDevice.current.model), iOS \(UIDevice.current.systemVersion).
        Your hands here are the listed tools: web search/fetch, files in Robo's own folder, real JavaScript execution, memory, reminders and calendar (with permission). There is no shell, no root and no filesystem outside Robo's folder on iOS — when a task genuinely needs a terminal, package installs, or arbitrary files, say so and suggest Gateway mode (this same app connected to a computer running `robo serve`). Never pretend to have run something you cannot run.
        Destructive tools stop for the user's approval; if they deny, stop and ask what to do next.
        Keep answers tight for a phone screen: lead with the result, then the evidence.
        """)
        let mem = (try? String(contentsOf: LocalToolbox.documents.appendingPathComponent("MEMORY.md"), encoding: .utf8)) ?? ""
        let user = (try? String(contentsOf: LocalToolbox.documents.appendingPathComponent("USER.md"), encoding: .utf8)) ?? ""
        if !mem.isEmpty { parts.append("# MEMORY.md (durable facts)\n" + mem.suffix(6000)) }
        if !user.isEmpty { parts.append("# USER.md (about the user)\n" + user.suffix(3000)) }
        return parts.joined(separator: "\n\n")
    }

    // MARK: - Turn

    public func send(_ text: String) {
        interrupted = false
        session.messages.append(ChatMessage(role: .user, content: text))
        if session.title == "New session" { session.title = String(text.prefix(48)) }
        persist()
        task = Task { await runTurn() }
    }

    public func interrupt() {
        interrupted = true
        task?.cancel()
    }

    private func emit(_ ev: GatewayEvent) { onEvent?(ev) }

    private func runTurn() async {
        let sid = session.id
        emit(.sessionInfo(session: sid, model: "\(config.kind.rawValue)/\(config.model)"))
        let provider = makeProvider(config)
        let tools = LocalToolbox.all()
        let specs = tools.map(\.spec)
        var iterations = 0

        while iterations < Self.maxIterations, !interrupted, !Task.isCancelled {
            iterations += 1
            await compactIfNeeded()
            let messages = [ChatMessage(role: .system, content: systemPrompt())] + session.messages

            emit(.messageStart(session: sid))
            actor Acc { var text = ""; var calls: [ToolCall] = []; var finish = "stop"
                func add(_ t: String) { text += t }; func call(_ c: ToolCall) { calls.append(c) }; func done(_ f: String) { finish = f } }
            let acc = Acc()
            do {
                try await provider.stream(messages: messages, tools: specs, config: config) { [weak self] chunk in
                    switch chunk {
                    case .text(let t): await acc.add(t); await MainActor.run { self?.emit(.messageDelta(session: sid, text: t)) }
                    case .reasoning(let r): await MainActor.run { self?.emit(.reasoningDelta(session: sid, text: r)) }
                    case .toolCall(let c): await acc.call(c)
                    case .usage(let i, let o): await MainActor.run { self?.totalInput += i; self?.totalOutput += o }
                    case .done(let f): await acc.done(f)
                    }
                }
            } catch {
                if Task.isCancelled || interrupted {
                    emit(.messageComplete(session: sid, text: "", status: "interrupted"))
                } else {
                    emit(.messageComplete(session: sid, text: "Robo could not reach the model: \(error.localizedDescription)", status: "error"))
                }
                persist(); return
            }
            let text = await acc.text
            let calls = await acc.calls
            session.messages.append(ChatMessage(role: .assistant, content: text, toolCalls: calls))
            persist()

            if calls.isEmpty || interrupted {
                emit(.messageComplete(session: sid, text: text, status: interrupted ? "interrupted" : "ok"))
                emit(.statusUpdate(session: sid, kind: "usage", text: "tokens in \(totalInput) · out \(totalOutput)"))
                return
            }
            // Tool phase — intermediate text (if any) already streamed; close that bubble.
            if !text.isEmpty { emit(.messageComplete(session: sid, text: text, status: "ok")) }
            for call in calls {
                if interrupted { break }
                let args = (try? JSONSerialization.jsonObject(with: Data(call.arguments.utf8)) as? [String: Any]) ?? [:]
                guard let tool = tools.first(where: { $0.spec.name == call.name }) else {
                    session.messages.append(ChatMessage(role: .tool, content: "unknown tool \(call.name)", toolCallId: call.id, name: call.name))
                    continue
                }
                let label = tool.describe(args)
                emit(.toolStart(session: sid, name: call.name, label: label))
                var result: LocalToolResult
                if tool.needsApproval && !sessionApproved.contains(call.name) && !(args["action"] as? String == "list") {
                    let choice = await approvalHandler?(ApprovalRequest(command: label, description: "\(call.name) can change data on this device", patternKeys: [call.name])) ?? "deny"
                    switch choice {
                    case "session": sessionApproved.insert(call.name); result = await tool.run(args)
                    case "once": result = await tool.run(args)
                    default:
                        result = LocalToolResult(text: "BLOCKED: the user denied \(call.name). Do not retry or work around it; ask what to do next.", isError: true)
                        interrupted = true
                    }
                } else {
                    result = await tool.run(args)
                }
                emit(.toolComplete(session: sid, name: call.name, ok: !result.isError))
                session.messages.append(ChatMessage(role: .tool, content: String(result.text.prefix(50_000)), toolCallId: call.id, name: call.name))
                persist()
            }
            if interrupted {
                emit(.messageComplete(session: sid, text: "Stopped. Tell Robo what to do next.", status: "interrupted"))
                emit(.statusUpdate(session: sid, kind: "approval", text: "Robo stopped"))
                return
            }
        }
        emit(.messageComplete(session: sid, text: "Reached the step limit for one turn (\(Self.maxIterations)). Ask Robo to continue.", status: "ok"))
    }

    // MARK: - Compaction: summarise the oldest turns when the transcript grows large.

    private func compactIfNeeded() async {
        let size = session.messages.reduce(0) { $0 + $1.content.count }
        guard size > Self.compactAtChars, session.messages.count > 12 else { return }
        let keepTail = 8
        let head = Array(session.messages.dropLast(keepTail))
        let tail = Array(session.messages.suffix(keepTail))
        let transcript = head.map { "[\($0.role.rawValue)] \($0.content.prefix(2000))" }.joined(separator: "\n")
        let prompt = [ChatMessage(role: .system, content: "Summarise this conversation so the assistant can continue it: goals, decisions, facts learned, files touched, open items. Dense, factual, under 600 words."),
                      ChatMessage(role: .user, content: String(transcript.suffix(120_000)))]
        actor Buf { var t = ""; func add(_ s: String) { t += s } }
        let buf = Buf()
        try? await makeProvider(config).stream(messages: prompt, tools: [], config: config) { chunk in
            if case .text(let t) = chunk { await buf.add(t) }
        }
        let summary = await buf.t
        guard !summary.isEmpty else { return }
        session.messages = [ChatMessage(role: .user, content: "[Context summary of earlier conversation]\n\(summary)"),
                            ChatMessage(role: .assistant, content: "Understood — continuing from that summary.")] + tail
        emit(.statusUpdate(session: session.id, kind: "compaction", text: "Context compacted"))
        persist()
    }
}
