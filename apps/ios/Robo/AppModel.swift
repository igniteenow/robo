// AppModel.swift — Robo iOS
// One observable model behind every screen: connection, the transcript of
// the active session, the pending approval prompt, and voice I/O. The
// transcript reducer mirrors the desktop's grouped tool runs: tool activity
// collapses to one row per turn that ticks with the latest tool, and expands
// on tap — the same "clean while it works" behaviour as the TUI/desktop.

import AVFoundation
import Foundation
import Security
import Speech
import SwiftUI

// MARK: - Transcript

public enum TranscriptItem: Identifiable, Equatable {
    case user(id: UUID, text: String)
    case assistant(id: UUID, text: String, streaming: Bool)
    case tools(id: UUID, entries: [ToolEntry], running: Bool)
    case status(id: UUID, text: String)

    public var id: UUID {
        switch self {
        case .user(let id, _), .assistant(let id, _, _), .tools(let id, _, _), .status(let id, _): return id
        }
    }
}

public struct ToolEntry: Equatable, Identifiable {
    public var id: String { name + label + "\(startedAt.timeIntervalSince1970)" }
    public var name: String
    public var label: String
    public var ok: Bool?
    public var startedAt: Date
}

// MARK: - Keychain (token never lives in UserDefaults)

enum Keychain {
    private static let service = "com.igniteenow.robo.gateway"

    static func save(_ value: String, for key: String) {
        let data = Data(value.utf8)
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: key]
        SecItemDelete(q as CFDictionary)
        var add = q
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }

    static func load(_ key: String) -> String? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: key, kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }

    static func delete(_ key: String) {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: key]
        SecItemDelete(q as CFDictionary)
    }
}

// MARK: - Voice

@MainActor
public final class VoiceController: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {
    @Published public var listening = false
    @Published public var transcript = ""
    @Published public var speaking = false
    @Published public var speakReplies = true

    private let synthesizer = AVSpeechSynthesizer()
    private let audioEngine = AVAudioEngine()
    private var recognizer: SFSpeechRecognizer? = SFSpeechRecognizer()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?

    public override init() {
        super.init()
        synthesizer.delegate = self
    }

    public func requestPermissions() async -> Bool {
        let speech = await withCheckedContinuation { c in SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0) } }
        let mic = await AVAudioApplication.requestRecordPermission()
        return speech == .authorized && mic
    }

    public func startListening() throws {
        guard let recognizer, recognizer.isAvailable else { throw NSError(domain: "robo.voice", code: 1, userInfo: [NSLocalizedDescriptionKey: "Speech recognition is not available."]) }
        stopSpeaking()
        transcript = ""
        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .defaultToSpeaker, .allowBluetooth])
        try audioSession.setActive(true, options: .notifyOthersOnDeactivation)
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
        request = req
        let input = audioEngine.inputNode
        let format = input.outputFormat(forBus: 0)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in req.append(buffer) }
        audioEngine.prepare()
        try audioEngine.start()
        listening = true
        recognitionTask = recognizer.recognitionTask(with: req) { [weak self] result, error in
            Task { @MainActor [weak self] in
                guard let self else { return }
                if let result { self.transcript = result.bestTranscription.formattedString }
                if error != nil || (result?.isFinal ?? false) { self.stopListening() }
            }
        }
    }

    public func stopListening() {
        guard listening else { return }
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        recognitionTask?.cancel()
        recognitionTask = nil
        request = nil
        listening = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    public func speak(_ text: String) {
        guard speakReplies else { return }
        let clean = text
            .replacingOccurrences(of: "```[\\s\\S]*?```", with: " code block ", options: .regularExpression)
            .replacingOccurrences(of: "[#*_`>]", with: "", options: .regularExpression)
        guard !clean.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        let u = AVSpeechUtterance(string: String(clean.prefix(1500)))
        u.voice = AVSpeechSynthesisVoice(language: Locale.current.identifier) ?? AVSpeechSynthesisVoice(language: "en-US")
        u.rate = AVSpeechUtteranceDefaultSpeechRate
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        speaking = true
        synthesizer.speak(u)
    }

    public func stopSpeaking() {
        if synthesizer.isSpeaking { synthesizer.stopSpeaking(at: .immediate) }
        speaking = false
    }

    public nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in self.speaking = false }
    }
}

// MARK: - App model

public enum RunMode: String, Codable { case local, gateway }

@MainActor
public final class AppModel: ObservableObject {
    @Published public var mode: RunMode = .local
    @Published public var provider: ProviderConfig?
    @Published public var endpoint: GatewayEndpoint?
    @Published public var sessionId: String?
    @Published public var items: [TranscriptItem] = []
    @Published public var busy = false
    @Published public var statusLine = ""
    @Published public var model = ""
    @Published public var approval: ApprovalRequest?
    @Published public var banner: String?
    @Published public var sessions: [(id: String, title: String)] = []

    public let client = GatewayClient()
    public let voice = VoiceController()
    public private(set) var local: LocalAgent?
    private var approvalContinuation: CheckedContinuation<String, Never>?

    private var streamingId: UUID?
    private var toolsId: UUID?
    private var replyBuffer = ""

    /// True once the app has enough to run in the current mode.
    public var configured: Bool { mode == .local ? provider != nil : endpoint != nil }

    public init() {
        client.onEvent = { [weak self] ev in self?.reduce(ev) }
        if let raw = UserDefaults.standard.string(forKey: "run.mode"), let m = RunMode(rawValue: raw) { mode = m }
        if let urlString = UserDefaults.standard.string(forKey: "gateway.url"),
           let url = URL(string: urlString), let token = Keychain.load("token") {
            endpoint = GatewayEndpoint(baseURL: url, accessToken: token)
        }
        if let data = UserDefaults.standard.data(forKey: "provider.config"), var cfg = try? JSONDecoder().decode(ProviderConfig.self, from: data) {
            cfg.apiKey = Keychain.load("provider.key") ?? ""
            provider = cfg
            startLocal(cfg)
        }
    }

    // MARK: local mode

    public func configureLocal(_ cfg: ProviderConfig) {
        var stored = cfg
        Keychain.save(cfg.apiKey, for: "provider.key")
        stored.apiKey = ""
        UserDefaults.standard.set(try? JSONEncoder().encode(stored), forKey: "provider.config")
        provider = cfg
        setMode(.local)
        startLocal(cfg)
    }

    public func setMode(_ m: RunMode) {
        mode = m
        UserDefaults.standard.set(m.rawValue, forKey: "run.mode")
        items = []
        if m == .gateway { Task { await connect() } } else { model = provider.map { "\($0.kind.rawValue)/\($0.model)" } ?? "" }
    }

    private func startLocal(_ cfg: ProviderConfig, session: LocalSession? = nil) {
        let agent = LocalAgent(config: cfg, session: session)
        agent.onEvent = { [weak self] ev in self?.reduce(ev) }
        agent.approvalHandler = { [weak self] req in
            guard let self else { return "deny" }
            self.approval = req
            self.statusLine = "Waiting for your approval"
            return await withCheckedContinuation { c in self.approvalContinuation = c }
        }
        local = agent
        sessionId = agent.session.id
        model = "\(cfg.kind.rawValue)/\(cfg.model)"
        items = agent.session.messages.compactMap { m in
            switch m.role {
            case .user: return .user(id: UUID(), text: m.content)
            case .assistant: return m.content.isEmpty ? nil : .assistant(id: UUID(), text: m.content, streaming: false)
            default: return nil
            }
        }
    }

    // MARK: pairing

    public func pair(_ ep: GatewayEndpoint) async {
        UserDefaults.standard.set(ep.baseURL.absoluteString, forKey: "gateway.url")
        Keychain.save(ep.accessToken, for: "token")
        endpoint = ep
        await connect()
    }

    public func unpair() {
        client.disconnect()
        Keychain.delete("token")
        UserDefaults.standard.removeObject(forKey: "gateway.url")
        endpoint = nil
        if mode == .gateway { sessionId = nil; items = [] }
    }

    public func connect() async {
        guard mode == .gateway, let ep = endpoint else { return }
        await client.connect(ep)
        // Give the socket a moment to open before the first RPC.
        for _ in 0..<40 where !client.connected { try? await Task.sleep(nanoseconds: 100_000_000) }
        guard client.connected else { banner = client.lastError ?? "Could not reach the gateway."; return }
        banner = nil
        if sessionId == nil {
            do { sessionId = try await client.createSession() } catch { banner = error.localizedDescription }
        }
        await refreshSessions()
    }

    public func refreshSessions() async {
        if mode == .local {
            sessions = LocalAgent.listSessions().map { ($0.id, $0.title) }
        } else {
            sessions = (try? await client.listSessions()) ?? []
        }
    }

    public func openSession(_ id: String) async {
        if mode == .local {
            guard let cfg = provider, let s = LocalAgent.load(id) else { return }
            startLocal(cfg, session: s)
            return
        }
        do {
            sessionId = try await client.resumeSession(id)
            items = [.status(id: UUID(), text: "Resumed session")]
        } catch { banner = error.localizedDescription }
    }

    public func newSession() async {
        if mode == .local {
            if let cfg = provider { startLocal(cfg) }
            items = []
            return
        }
        do {
            sessionId = try await client.createSession()
            items = []
        } catch { banner = error.localizedDescription }
    }

    // MARK: chat

    public func send(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        if mode == .local {
            guard let agent = local else { banner = "Add a provider and API key in Settings."; return }
            items.append(.user(id: UUID(), text: trimmed))
            busy = true
            agent.send(trimmed)
            return
        }
        guard let sid = sessionId else { return }
        items.append(.user(id: UUID(), text: trimmed))
        busy = true
        do {
            let status = try await client.submit(trimmed, session: sid)
            if status == "queued" { statusLine = "Queued — Robo will read it next" }
        } catch {
            busy = false
            items.append(.status(id: UUID(), text: "Send failed: \(error.localizedDescription)"))
        }
    }

    public func stop() async {
        if mode == .local { local?.interrupt(); return }
        guard let sid = sessionId else { return }
        try? await client.interrupt(session: sid)
    }

    public func answerApproval(_ choice: String) async {
        approval = nil
        if mode == .local {
            approvalContinuation?.resume(returning: choice)
            approvalContinuation = nil
            return
        }
        guard let sid = sessionId else { return }
        try? await client.respondApproval(session: sid, choice: choice)
    }

    // MARK: reducer

    private func reduce(_ ev: GatewayEvent) {
        switch ev {
        case .sessionInfo(_, let m):
            if !m.isEmpty { model = m }
        case .messageStart:
            busy = true
            replyBuffer = ""
            let id = UUID()
            streamingId = id
            items.append(.assistant(id: id, text: "", streaming: true))
        case .messageDelta(_, let text):
            replyBuffer += text
            updateStreaming(replyBuffer, streaming: true)
        case .reasoningDelta:
            statusLine = "Thinking…"
        case .messageComplete(_, let text, let status):
            let final = text.isEmpty ? replyBuffer : text
            updateStreaming(final, streaming: false)
            streamingId = nil
            busy = false
            statusLine = status == "ok" ? "" : status
            closeTools()
            if status == "ok" || status == "complete" { voice.speak(final) }
        case .toolStart(_, let name, let label):
            let entry = ToolEntry(name: name, label: label, ok: nil, startedAt: Date())
            if let tid = toolsId, let idx = items.firstIndex(where: { $0.id == tid }),
               case .tools(_, var entries, _) = items[idx] {
                entries.append(entry)
                items[idx] = .tools(id: tid, entries: entries, running: true)
            } else {
                let tid = UUID()
                toolsId = tid
                items.append(.tools(id: tid, entries: [entry], running: true))
            }
            statusLine = label
        case .toolComplete(_, let name, let ok):
            if let tid = toolsId, let idx = items.firstIndex(where: { $0.id == tid }),
               case .tools(_, var entries, let running) = items[idx],
               let last = entries.lastIndex(where: { $0.name == name && $0.ok == nil }) {
                entries[last].ok = ok
                items[idx] = .tools(id: tid, entries: entries, running: running)
            }
        case .statusUpdate(_, let kind, let text):
            statusLine = text
            if kind == "approval" && text.contains("stopped") { busy = false }
        case .approvalRequest(_, let req):
            approval = req
            statusLine = "Waiting for your approval"
        case .userMessage(_, let text):
            // Authoritative echo of a mid-turn message; skip if we already show it.
            if case .user(_, let last)? = items.last(where: { if case .user = $0 { return true } else { return false } }), last == text { return }
            items.append(.user(id: UUID(), text: text))
        case .unknown:
            break
        }
    }

    private func updateStreaming(_ text: String, streaming: Bool) {
        guard let sid = streamingId, let idx = items.firstIndex(where: { $0.id == sid }) else {
            let id = UUID()
            streamingId = id
            items.append(.assistant(id: id, text: text, streaming: streaming))
            return
        }
        items[idx] = .assistant(id: sid, text: text, streaming: streaming)
    }

    private func closeTools() {
        if let tid = toolsId, let idx = items.firstIndex(where: { $0.id == tid }), case .tools(_, let entries, _) = items[idx] {
            items[idx] = .tools(id: tid, entries: entries, running: false)
        }
        toolsId = nil
    }
}
