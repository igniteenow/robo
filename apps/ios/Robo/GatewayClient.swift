// GatewayClient.swift — Robo iOS
// JSON-RPC 2.0 over WebSocket to a Robo gateway (`robo serve`), the same
// transport the desktop app and the web dashboard use:
//
//   wss://<host>:<port>/api/ws?ticket=<single-use ticket>   (gated auth)
//   ws://127.0.0.1:<port>/api/ws?token=<session token>       (loopback / --insecure)
//
// Requests:  {"jsonrpc":"2.0","id":n,"method":"session.create","params":{…}}
// Responses: {"jsonrpc":"2.0","id":n,"result":{…}} | {"id":n,"error":{"code","message"}}
// Events:    {"jsonrpc":"2.0","method":"event","params":{"type":"message.delta","session_id":"…","payload":{…}}}
//
// Nothing here executes on the phone: every tool call runs on the gateway
// machine, and dangerous commands stop there until the user answers the
// approval prompt this client shows.

import Foundation

public struct GatewayEndpoint: Codable, Equatable, Sendable {
    public var baseURL: URL          // e.g. https://robo.example.com:8642 or http://192.168.1.20:8642
    public var accessToken: String   // dashboard session/API token (kept in Keychain)

    public init(baseURL: URL, accessToken: String) {
        self.baseURL = baseURL
        self.accessToken = accessToken
    }

    /// Parse the pairing string `robo serve --pair` prints (and encodes as a QR):
    /// `robo://pair?url=<base-url>&token=<token>`.
    public static func fromPairingString(_ raw: String) -> GatewayEndpoint? {
        guard let comps = URLComponents(string: raw.trimmingCharacters(in: .whitespacesAndNewlines)),
              comps.scheme == "robo", comps.host == "pair" else { return nil }
        var url: URL?
        var token = ""
        for item in comps.queryItems ?? [] {
            if item.name == "url", let v = item.value { url = URL(string: v) }
            if item.name == "token", let v = item.value { token = v }
        }
        guard let u = url, !token.isEmpty else { return nil }
        return GatewayEndpoint(baseURL: u, accessToken: token)
    }

    var wsScheme: String { baseURL.scheme?.lowercased() == "https" ? "wss" : "ws" }
}

public enum GatewayEvent: Sendable, Equatable {
    case messageStart(session: String)
    case messageDelta(session: String, text: String)
    case messageComplete(session: String, text: String, status: String)
    case reasoningDelta(session: String, text: String)
    case toolStart(session: String, name: String, label: String)
    case toolComplete(session: String, name: String, ok: Bool)
    case statusUpdate(session: String, kind: String, text: String)
    case approvalRequest(session: String, request: ApprovalRequest)
    case userMessage(session: String, text: String)
    case sessionInfo(session: String, model: String)
    case unknown(type: String)
}

public struct ApprovalRequest: Sendable, Equatable, Identifiable {
    public var id: String { command + description }
    public let command: String
    public let description: String
    public let patternKeys: [String]
}

public enum GatewayError: Error, LocalizedError, Sendable, Equatable {
    case notConnected
    case authFailed(String)
    case rpc(code: Int, message: String)
    case transport(String)
    case decoding

    public var errorDescription: String? {
        switch self {
        case .notConnected: return "Not connected to a Robo gateway."
        case .authFailed(let why): return "The gateway rejected the token (\(why))."
        case .rpc(let code, let message): return "\(message) (code \(code))"
        case .transport(let why): return why
        case .decoding: return "Unreadable frame from the gateway."
        }
    }
}

/// Pure JSON-RPC framing (no networking) so it can be unit-tested.
public enum RPCFrames {
    public static func request(id: Int, method: String, params: [String: Any]) throws -> Data {
        let obj: [String: Any] = ["jsonrpc": "2.0", "id": id, "method": method, "params": params]
        return try JSONSerialization.data(withJSONObject: obj)
    }

    public enum Incoming: Equatable {
        case response(id: Int, result: [String: Any]?, error: (code: Int, message: String)?)
        case event(GatewayEvent)

        public static func == (lhs: Incoming, rhs: Incoming) -> Bool {
            switch (lhs, rhs) {
            case let (.event(a), .event(b)): return a == b
            case let (.response(ia, _, ea), .response(ib, _, eb)): return ia == ib && ea?.code == eb?.code
            default: return false
            }
        }
    }

    public static func parse(_ data: Data) -> Incoming? {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        if let id = obj["id"] as? Int {
            if let err = obj["error"] as? [String: Any] {
                return .response(id: id, result: nil,
                                 error: (err["code"] as? Int ?? -1, err["message"] as? String ?? "error"))
            }
            return .response(id: id, result: obj["result"] as? [String: Any], error: nil)
        }
        guard obj["method"] as? String == "event", let params = obj["params"] as? [String: Any] else { return nil }
        return .event(parseEvent(params))
    }

    public static func parseEvent(_ p: [String: Any]) -> GatewayEvent {
        let type = p["type"] as? String ?? ""
        let sid = p["session_id"] as? String ?? ""
        let payload = p["payload"] as? [String: Any] ?? [:]
        let text = payload["text"] as? String ?? ""
        switch type {
        case "message.start": return .messageStart(session: sid)
        case "message.delta": return .messageDelta(session: sid, text: text)
        case "message.complete": return .messageComplete(session: sid, text: text, status: payload["status"] as? String ?? "ok")
        case "reasoning.delta": return .reasoningDelta(session: sid, text: text)
        case "tool.start":
            let name = payload["name"] as? String ?? payload["tool"] as? String ?? "tool"
            return .toolStart(session: sid, name: name, label: payload["label"] as? String ?? payload["summary"] as? String ?? name)
        case "tool.complete":
            let name = payload["name"] as? String ?? payload["tool"] as? String ?? "tool"
            let status = payload["status"] as? String ?? "ok"
            return .toolComplete(session: sid, name: name, ok: status != "error")
        case "status.update": return .statusUpdate(session: sid, kind: payload["kind"] as? String ?? "", text: text)
        case "approval.request":
            return .approvalRequest(session: sid, request: ApprovalRequest(
                command: payload["command"] as? String ?? "",
                description: payload["description"] as? String ?? "",
                patternKeys: payload["pattern_keys"] as? [String] ?? []))
        case "message.user": return .userMessage(session: sid, text: text)
        case "session.info": return .sessionInfo(session: sid, model: payload["model"] as? String ?? "")
        default: return .unknown(type: type)
        }
    }
}

@MainActor
public final class GatewayClient: NSObject, ObservableObject {
    @Published public private(set) var connected = false
    @Published public private(set) var lastError: String?
    public var onEvent: (@MainActor (GatewayEvent) -> Void)?

    private var task: URLSessionWebSocketTask?
    private var session: URLSession!
    private var nextId = 1
    private var pending: [Int: CheckedContinuation<[String: Any], Error>] = [:]
    private var endpoint: GatewayEndpoint?
    private var reconnectAttempts = 0
    private var wantConnection = false

    public override init() {
        super.init()
        let cfg = URLSessionConfiguration.default
        cfg.waitsForConnectivity = true
        session = URLSession(configuration: cfg, delegate: self, delegateQueue: nil)
    }

    // MARK: - Connect / auth

    public func connect(_ ep: GatewayEndpoint) async {
        endpoint = ep
        wantConnection = true
        await open()
    }

    public func disconnect() {
        wantConnection = false
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        connected = false
        failAllPending(GatewayError.notConnected)
    }

    private func open() async {
        guard let ep = endpoint else { return }
        var comps = URLComponents(url: ep.baseURL.appendingPathComponent("api/ws"), resolvingAgainstBaseURL: false)!
        comps.scheme = ep.wsScheme
        // Gated gateways only accept a single-use ticket on the upgrade; mint
        // one with the bearer token. Loopback / --insecure gateways accept the
        // token directly, so fall back to ?token= when the ticket route is absent.
        if let ticket = await mintTicket(ep) {
            comps.queryItems = [URLQueryItem(name: "ticket", value: ticket)]
        } else {
            comps.queryItems = [URLQueryItem(name: "token", value: ep.accessToken)]
        }
        var req = URLRequest(url: comps.url!)
        req.setValue("Bearer \(ep.accessToken)", forHTTPHeaderField: "Authorization")
        req.setValue("robo-ios/3.0", forHTTPHeaderField: "User-Agent")
        let t = session.webSocketTask(with: req)
        task = t
        t.resume()
        receiveLoop(t)
    }

    private func mintTicket(_ ep: GatewayEndpoint) async -> String? {
        var req = URLRequest(url: ep.baseURL.appendingPathComponent("api/auth/ws-ticket"))
        req.httpMethod = "POST"
        req.setValue("Bearer \(ep.accessToken)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        guard let (data, resp) = try? await session.data(for: req),
              let http = resp as? HTTPURLResponse else { return nil }
        if http.statusCode == 401 || http.statusCode == 403 {
            lastError = GatewayError.authFailed("HTTP \(http.statusCode)").localizedDescription
            return nil
        }
        guard http.statusCode == 200,
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return obj["ticket"] as? String
    }

    private func receiveLoop(_ t: URLSessionWebSocketTask) {
        t.receive { [weak self] result in
            Task { @MainActor [weak self] in
                guard let self, self.task === t else { return }
                switch result {
                case .failure(let err):
                    self.connected = false
                    self.lastError = err.localizedDescription
                    self.failAllPending(GatewayError.transport(err.localizedDescription))
                    await self.scheduleReconnect()
                case .success(let msg):
                    let data: Data
                    switch msg {
                    case .data(let d): data = d
                    case .string(let s): data = Data(s.utf8)
                    @unknown default: data = Data()
                    }
                    self.handle(data)
                    self.receiveLoop(t)
                }
            }
        }
    }

    private func handle(_ data: Data) {
        guard let frame = RPCFrames.parse(data) else { return }
        switch frame {
        case .response(let id, let result, let error):
            guard let cont = pending.removeValue(forKey: id) else { return }
            if let e = error { cont.resume(throwing: GatewayError.rpc(code: e.code, message: e.message)) }
            else { cont.resume(returning: result ?? [:]) }
        case .event(let ev):
            onEvent?(ev)
        }
    }

    private func scheduleReconnect() async {
        guard wantConnection else { return }
        reconnectAttempts += 1
        let delay = min(30.0, pow(2.0, Double(min(reconnectAttempts, 5))))
        try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
        guard wantConnection else { return }
        await open()
    }

    private func failAllPending(_ error: Error) {
        for (_, c) in pending { c.resume(throwing: error) }
        pending.removeAll()
    }

    // MARK: - RPC

    @discardableResult
    public func call(_ method: String, _ params: [String: Any] = [:]) async throws -> [String: Any] {
        guard let t = task, connected else { throw GatewayError.notConnected }
        let id = nextId
        nextId += 1
        let data = try RPCFrames.request(id: id, method: method, params: params)
        return try await withCheckedThrowingContinuation { cont in
            pending[id] = cont
            t.send(.data(data)) { [weak self] err in
                guard let err else { return }
                Task { @MainActor [weak self] in
                    self?.pending.removeValue(forKey: id)?.resume(throwing: GatewayError.transport(err.localizedDescription))
                }
            }
        }
    }

    // Typed helpers over the gateway methods the app uses.
    public func createSession(title: String = "iPhone") async throws -> String {
        let r = try await call("session.create", ["title": title, "source": "ios", "cols": 60])
        guard let sid = r["session_id"] as? String else { throw GatewayError.decoding }
        return sid
    }

    public func listSessions(limit: Int = 50) async throws -> [(id: String, title: String)] {
        let r = try await call("session.list", ["limit": limit])
        let rows = r["sessions"] as? [[String: Any]] ?? []
        return rows.compactMap { row in
            guard let id = row["id"] as? String else { return nil }
            return (id, row["title"] as? String ?? "")
        }
    }

    public func resumeSession(_ id: String) async throws -> String {
        let r = try await call("session.resume", ["session_id": id, "cols": 60])
        return r["session_id"] as? String ?? id
    }

    public func submit(_ text: String, session: String) async throws -> String {
        let r = try await call("prompt.submit", ["session_id": session, "text": text])
        return r["status"] as? String ?? "ok"
    }

    public func interrupt(session: String) async throws {
        _ = try await call("session.interrupt", ["session_id": session])
    }

    /// `choice` is "once" (allow), "session" (allow for this session) or "deny".
    public func respondApproval(session: String, choice: String, reason: String? = nil) async throws {
        var p: [String: Any] = ["session_id": session, "choice": choice]
        if let reason, !reason.isEmpty { p["reason"] = reason }
        _ = try await call("approval.respond", p)
    }
}

extension GatewayClient: URLSessionWebSocketDelegate {
    public nonisolated func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                                       didOpenWithProtocol protocol: String?) {
        Task { @MainActor in
            self.connected = true
            self.reconnectAttempts = 0
            self.lastError = nil
        }
    }

    public nonisolated func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                                       didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        Task { @MainActor in
            self.connected = false
            if closeCode == .policyViolation || closeCode == .internalServerError {
                self.lastError = GatewayError.authFailed("close code \(closeCode.rawValue)").localizedDescription
            }
            await self.scheduleReconnect()
        }
    }
}
