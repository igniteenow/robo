// Providers.swift — Robo iOS · Local mode
// The agent loop on the phone talks to model providers directly with the
// user's API key. Two wire formats cover the market:
//   * OpenAI-compatible chat completions (OpenAI, OpenRouter, Groq, xAI,
//     DeepSeek, Mistral, Together, Ollama/LM Studio over the network, …)
//   * Anthropic Messages API
// Both stream tokens over SSE and surface tool calls in one common shape so
// the agent loop (LocalAgent.swift) never sees provider differences.

import Foundation

public enum ProviderKind: String, Codable, CaseIterable, Sendable {
    case openai, openrouter, anthropic, groq, xai, deepseek, mistral, custom

    public var label: String {
        switch self {
        case .openai: return "OpenAI"
        case .openrouter: return "OpenRouter"
        case .anthropic: return "Anthropic"
        case .groq: return "Groq"
        case .xai: return "xAI"
        case .deepseek: return "DeepSeek"
        case .mistral: return "Mistral"
        case .custom: return "Custom (OpenAI-compatible)"
        }
    }

    public var defaultBaseURL: String {
        switch self {
        case .openai: return "https://api.openai.com/v1"
        case .openrouter: return "https://openrouter.ai/api/v1"
        case .anthropic: return "https://api.anthropic.com/v1"
        case .groq: return "https://api.groq.com/openai/v1"
        case .xai: return "https://api.x.ai/v1"
        case .deepseek: return "https://api.deepseek.com/v1"
        case .mistral: return "https://api.mistral.ai/v1"
        case .custom: return "http://localhost:11434/v1"
        }
    }

    public var defaultModel: String {
        switch self {
        case .openai: return "gpt-5"
        case .openrouter: return "anthropic/claude-sonnet-5"
        case .anthropic: return "claude-sonnet-5"
        case .groq: return "llama-4-scout"
        case .xai: return "grok-4-fast"
        case .deepseek: return "deepseek-chat"
        case .mistral: return "mistral-large-latest"
        case .custom: return "llama3"
        }
    }
}

public struct ProviderConfig: Codable, Equatable, Sendable {
    public var kind: ProviderKind
    public var baseURL: String
    public var model: String
    public var apiKey: String
    public var reasoningEffort: String = "high"     // deep thinking is Robo's default posture
    public var maxTokens: Int = 8192

    public init(kind: ProviderKind, baseURL: String? = nil, model: String? = nil, apiKey: String) {
        self.kind = kind
        self.baseURL = baseURL ?? kind.defaultBaseURL
        self.model = model ?? kind.defaultModel
        self.apiKey = apiKey
    }
}

// MARK: - Common message model

public enum ChatRole: String, Codable, Sendable { case system, user, assistant, tool }

public struct ToolCall: Codable, Equatable, Sendable, Identifiable {
    public var id: String
    public var name: String
    public var arguments: String   // raw JSON text
    public init(id: String, name: String, arguments: String) { self.id = id; self.name = name; self.arguments = arguments }
}

public struct ChatMessage: Codable, Equatable, Sendable {
    public var role: ChatRole
    public var content: String
    public var toolCalls: [ToolCall] = []
    public var toolCallId: String? = nil    // for role == .tool
    public var name: String? = nil

    public init(role: ChatRole, content: String, toolCalls: [ToolCall] = [], toolCallId: String? = nil, name: String? = nil) {
        self.role = role; self.content = content; self.toolCalls = toolCalls; self.toolCallId = toolCallId; self.name = name
    }
}

public struct ToolSpec: Codable, Sendable {
    public var name: String
    public var description: String
    public var parameters: [String: AnyCodable]   // JSON schema
}

public enum StreamChunk: Sendable, Equatable {
    case text(String)
    case reasoning(String)
    case toolCall(ToolCall)
    case usage(input: Int, output: Int)
    case done(finishReason: String)
}

public enum ProviderError: Error, LocalizedError {
    case http(Int, String)
    case badResponse(String)
    case missingKey

    public var errorDescription: String? {
        switch self {
        case .http(let code, let body): return "Provider returned HTTP \(code): \(body.prefix(300))"
        case .badResponse(let why): return "Unexpected provider response: \(why)"
        case .missingKey: return "No API key configured for this provider."
        }
    }
}

// MARK: - AnyCodable (tiny, for JSON schema payloads)

public struct AnyCodable: Codable, Sendable, Equatable {
    public let value: Any

    public init(_ value: Any) { self.value = value }

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { value = NSNull() }
        else if let b = try? c.decode(Bool.self) { value = b }
        else if let i = try? c.decode(Int.self) { value = i }
        else if let d = try? c.decode(Double.self) { value = d }
        else if let s = try? c.decode(String.self) { value = s }
        else if let a = try? c.decode([AnyCodable].self) { value = a.map(\.value) }
        else if let o = try? c.decode([String: AnyCodable].self) { value = o.mapValues(\.value) }
        else { throw DecodingError.dataCorruptedError(in: c, debugDescription: "unsupported JSON") }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch value {
        case is NSNull: try c.encodeNil()
        case let b as Bool: try c.encode(b)
        case let i as Int: try c.encode(i)
        case let d as Double: try c.encode(d)
        case let s as String: try c.encode(s)
        case let a as [Any]: try c.encode(a.map(AnyCodable.init))
        case let o as [String: Any]: try c.encode(o.mapValues(AnyCodable.init))
        default: try c.encode(String(describing: value))
        }
    }

    public static func == (lhs: AnyCodable, rhs: AnyCodable) -> Bool {
        String(describing: lhs.value) == String(describing: rhs.value)
    }
}

// MARK: - SSE parsing (pure, unit-tested)

public enum SSE {
    /// Split a raw SSE byte stream into `data:` payloads. Handles multi-line
    /// data fields and CRLF. `[DONE]` is passed through so callers can stop.
    public static func events(from text: String) -> [String] {
        var out: [String] = []
        var current: [String] = []
        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = rawLine.hasSuffix("\r") ? String(rawLine.dropLast()) : String(rawLine)
            if line.isEmpty {
                if !current.isEmpty { out.append(current.joined(separator: "\n")); current.removeAll() }
                continue
            }
            if line.hasPrefix(":") { continue }
            if line.hasPrefix("data:") {
                var v = String(line.dropFirst(5))
                if v.hasPrefix(" ") { v.removeFirst() }
                current.append(v)
            }
        }
        if !current.isEmpty { out.append(current.joined(separator: "\n")) }
        return out
    }
}

// MARK: - Provider protocol

public protocol ChatProvider: Sendable {
    func stream(messages: [ChatMessage], tools: [ToolSpec], config: ProviderConfig,
                onChunk: @escaping @Sendable (StreamChunk) async -> Void) async throws
}

public func makeProvider(_ config: ProviderConfig) -> ChatProvider {
    config.kind == .anthropic ? AnthropicProvider() : OpenAICompatibleProvider()
}

private func jsonObject(_ obj: Any) throws -> Data { try JSONSerialization.data(withJSONObject: obj) }

private func readSSE(_ req: URLRequest, onEvent: @escaping @Sendable (String) async -> Bool) async throws {
    let (bytes, resp) = try await URLSession.shared.bytes(for: req)
    guard let http = resp as? HTTPURLResponse else { throw ProviderError.badResponse("no HTTP response") }
    if http.statusCode >= 400 {
        var body = ""
        for try await line in bytes.lines { body += line + "\n"; if body.count > 4000 { break } }
        throw ProviderError.http(http.statusCode, body)
    }
    var buffer = ""
    for try await line in bytes.lines {
        if line.isEmpty {
            for ev in SSE.events(from: buffer + "\n\n") {
                if await onEvent(ev) == false { return }
            }
            buffer = ""
        } else {
            buffer += line + "\n"
        }
    }
    if !buffer.isEmpty {
        for ev in SSE.events(from: buffer + "\n\n") { _ = await onEvent(ev) }
    }
}

// MARK: - OpenAI-compatible

public struct OpenAICompatibleProvider: ChatProvider {
    public init() {}

    public func stream(messages: [ChatMessage], tools: [ToolSpec], config: ProviderConfig,
                       onChunk: @escaping @Sendable (StreamChunk) async -> Void) async throws {
        guard !config.apiKey.isEmpty || config.kind == .custom else { throw ProviderError.missingKey }
        var msgs: [[String: Any]] = []
        for m in messages {
            var o: [String: Any] = ["role": m.role.rawValue, "content": m.content]
            if !m.toolCalls.isEmpty {
                o["tool_calls"] = m.toolCalls.map { ["id": $0.id, "type": "function", "function": ["name": $0.name, "arguments": $0.arguments]] }
                if m.content.isEmpty { o["content"] = NSNull() }
            }
            if let tid = m.toolCallId { o["tool_call_id"] = tid }
            msgs.append(o)
        }
        var body: [String: Any] = ["model": config.model, "messages": msgs, "stream": true, "max_tokens": config.maxTokens,
                                   "stream_options": ["include_usage": true]]
        if !tools.isEmpty {
            body["tools"] = tools.map { t -> [String: Any] in
                let params = try? JSONSerialization.jsonObject(with: JSONEncoder().encode(t.parameters))
                return ["type": "function", "function": ["name": t.name, "description": t.description, "parameters": params ?? [:]]]
            }
        }
        if !config.reasoningEffort.isEmpty, config.reasoningEffort != "none" {
            body["reasoning_effort"] = config.reasoningEffort          // OpenAI / xAI / DeepSeek style
            if config.kind == .openrouter { body["reasoning"] = ["effort": config.reasoningEffort] }
        }
        var req = URLRequest(url: URL(string: config.baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/chat/completions")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        if !config.apiKey.isEmpty { req.setValue("Bearer \(config.apiKey)", forHTTPHeaderField: "Authorization") }
        if config.kind == .openrouter {
            req.setValue("https://igniteenow.com/robo", forHTTPHeaderField: "HTTP-Referer")
            req.setValue("Robo for iOS", forHTTPHeaderField: "X-Title")
        }
        req.httpBody = try jsonObject(body)
        req.timeoutInterval = 300

        // Tool-call deltas arrive fragmented by index; assemble before emitting.
        actor Assembler {
            var calls: [Int: (id: String, name: String, args: String)] = [:]
            func add(index: Int, id: String?, name: String?, args: String?) {
                var c = calls[index] ?? ("", "", "")
                if let id, !id.isEmpty { c.id = id }
                if let name, !name.isEmpty { c.name = name }
                if let args { c.args += args }
                calls[index] = c
            }
            func drain() -> [ToolCall] {
                calls.keys.sorted().compactMap { k in
                    guard let c = calls[k], !c.name.isEmpty else { return nil }
                    return ToolCall(id: c.id.isEmpty ? "call_\(k)" : c.id, name: c.name, arguments: c.args.isEmpty ? "{}" : c.args)
                }
            }
            var finish = "stop"
            func setFinish(_ f: String) { finish = f }
        }
        let asm = Assembler()
        try await readSSE(req) { ev in
            if ev == "[DONE]" { return false }
            guard let data = ev.data(using: .utf8), let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return true }
            if let usage = obj["usage"] as? [String: Any] {
                await onChunk(.usage(input: usage["prompt_tokens"] as? Int ?? 0, output: usage["completion_tokens"] as? Int ?? 0))
            }
            guard let choice = (obj["choices"] as? [[String: Any]])?.first else { return true }
            if let fr = choice["finish_reason"] as? String { await asm.setFinish(fr) }
            guard let delta = choice["delta"] as? [String: Any] else { return true }
            if let t = delta["content"] as? String, !t.isEmpty { await onChunk(.text(t)) }
            if let r = (delta["reasoning_content"] as? String) ?? (delta["reasoning"] as? String), !r.isEmpty { await onChunk(.reasoning(r)) }
            if let tcs = delta["tool_calls"] as? [[String: Any]] {
                for tc in tcs {
                    let fn = tc["function"] as? [String: Any] ?? [:]
                    await asm.add(index: tc["index"] as? Int ?? 0, id: tc["id"] as? String, name: fn["name"] as? String, args: fn["arguments"] as? String)
                }
            }
            return true
        }
        for call in await asm.drain() { await onChunk(.toolCall(call)) }
        await onChunk(.done(finishReason: await asm.finish))
    }
}

// MARK: - Anthropic Messages API

public struct AnthropicProvider: ChatProvider {
    public init() {}

    public func stream(messages: [ChatMessage], tools: [ToolSpec], config: ProviderConfig,
                       onChunk: @escaping @Sendable (StreamChunk) async -> Void) async throws {
        guard !config.apiKey.isEmpty else { throw ProviderError.missingKey }
        var system = ""
        var msgs: [[String: Any]] = []
        for m in messages {
            switch m.role {
            case .system: system += (system.isEmpty ? "" : "\n\n") + m.content
            case .user: msgs.append(["role": "user", "content": m.content])
            case .assistant:
                var blocks: [[String: Any]] = []
                if !m.content.isEmpty { blocks.append(["type": "text", "text": m.content]) }
                for tc in m.toolCalls {
                    let input = (try? JSONSerialization.jsonObject(with: Data(tc.arguments.utf8))) ?? [:]
                    blocks.append(["type": "tool_use", "id": tc.id, "name": tc.name, "input": input])
                }
                msgs.append(["role": "assistant", "content": blocks.isEmpty ? [["type": "text", "text": " "]] : blocks])
            case .tool:
                let block: [String: Any] = ["type": "tool_result", "tool_use_id": m.toolCallId ?? "", "content": m.content]
                // Consecutive tool results must share one user turn.
                if let last = msgs.last, last["role"] as? String == "user", var content = last["content"] as? [[String: Any]],
                   content.first?["type"] as? String == "tool_result" {
                    content.append(block); msgs[msgs.count - 1]["content"] = content
                } else {
                    msgs.append(["role": "user", "content": [block]])
                }
            }
        }
        var body: [String: Any] = ["model": config.model, "messages": msgs, "max_tokens": config.maxTokens, "stream": true]
        if !system.isEmpty { body["system"] = system }
        if !tools.isEmpty {
            body["tools"] = tools.map { t -> [String: Any] in
                let params = (try? JSONSerialization.jsonObject(with: JSONEncoder().encode(t.parameters))) ?? ["type": "object"]
                return ["name": t.name, "description": t.description, "input_schema": params]
            }
        }
        if config.reasoningEffort != "none" && !config.reasoningEffort.isEmpty {
            let budget = ["low": 2048, "medium": 8192, "high": 16384, "xhigh": 32000, "max": 32000][config.reasoningEffort] ?? 16384
            body["thinking"] = ["type": "enabled", "budget_tokens": budget]
            body["max_tokens"] = max(config.maxTokens, budget + 4096)
        }
        var req = URLRequest(url: URL(string: config.baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/messages")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue(config.apiKey, forHTTPHeaderField: "x-api-key")
        req.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")
        req.httpBody = try jsonObject(body)
        req.timeoutInterval = 300

        actor Blocks {
            var open: [Int: (type: String, id: String, name: String, json: String)] = [:]
            var finished: [ToolCall] = []
            func start(_ i: Int, type: String, id: String, name: String) { open[i] = (type, id, name, "") }
            func append(_ i: Int, _ s: String) { open[i]?.json += s }
            func stop(_ i: Int) {
                if let b = open.removeValue(forKey: i), b.type == "tool_use" {
                    finished.append(ToolCall(id: b.id, name: b.name, arguments: b.json.isEmpty ? "{}" : b.json))
                }
            }
            func drain() -> [ToolCall] { defer { finished.removeAll() }; return finished }
            var finish = "end_turn"
            func setFinish(_ f: String) { finish = f }
        }
        let blocks = Blocks()
        try await readSSE(req) { ev in
            guard let data = ev.data(using: .utf8), let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let type = obj["type"] as? String else { return true }
            switch type {
            case "content_block_start":
                let cb = obj["content_block"] as? [String: Any] ?? [:]
                await blocks.start(obj["index"] as? Int ?? 0, type: cb["type"] as? String ?? "", id: cb["id"] as? String ?? "", name: cb["name"] as? String ?? "")
            case "content_block_delta":
                let d = obj["delta"] as? [String: Any] ?? [:]
                switch d["type"] as? String {
                case "text_delta": if let t = d["text"] as? String { await onChunk(.text(t)) }
                case "thinking_delta": if let t = d["thinking"] as? String { await onChunk(.reasoning(t)) }
                case "input_json_delta": await blocks.append(obj["index"] as? Int ?? 0, d["partial_json"] as? String ?? "")
                default: break
                }
            case "content_block_stop":
                await blocks.stop(obj["index"] as? Int ?? 0)
            case "message_delta":
                if let d = obj["delta"] as? [String: Any], let fr = d["stop_reason"] as? String { await blocks.setFinish(fr) }
                if let u = obj["usage"] as? [String: Any] { await onChunk(.usage(input: u["input_tokens"] as? Int ?? 0, output: u["output_tokens"] as? Int ?? 0)) }
            case "error":
                let e = obj["error"] as? [String: Any] ?? [:]
                await onChunk(.text("\n[provider error: \(e["message"] as? String ?? "unknown")]"))
                return false
            default: break
            }
            return true
        }
        for call in await blocks.drain() { await onChunk(.toolCall(call)) }
        let finish = await blocks.finish
        await onChunk(.done(finishReason: finish == "tool_use" ? "tool_calls" : "stop"))
    }
}
