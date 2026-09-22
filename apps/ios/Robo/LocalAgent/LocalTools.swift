// LocalTools.swift — Robo iOS · Local mode
// The "hands" Robo has when it runs on the phone itself. iOS has no shell,
// no root and no filesystem outside the app sandbox, so these tools are what
// an iPhone can genuinely do: reach the web, keep and edit its own files and
// memory, run real code in the built-in JavaScript engine, and act on the
// user's reminders and calendar with permission. Anything beyond that
// (terminals, package managers, editing arbitrary files, Docker, Ghidra…) is
// what Gateway mode is for — the same app, pointed at a machine.
//
// Destructive tools (writing/deleting files, creating reminders/events)
// carry `needsApproval` and stop the turn until the user answers the same
// Allow / Allow-for-session / Deny sheet used for gateway approvals.

import EventKit
import Foundation
import JavaScriptCore

public struct LocalToolResult: Sendable {
    public var text: String
    public var isError: Bool = false
}

public struct LocalTool: Sendable {
    public var spec: ToolSpec
    public var needsApproval: Bool
    public var describe: @Sendable ([String: Any]) -> String
    public var run: @Sendable ([String: Any]) async -> LocalToolResult
}

public enum LocalToolbox {
    public static var documents: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }

    public static func all() -> [LocalTool] {
        [webSearch, webFetch, listFiles, readFile, writeFile, runJavaScript, memory, reminders, calendar, currentTime]
    }

    private static func schema(_ props: [String: [String: Any]], required: [String]) -> [String: AnyCodable] {
        var p: [String: Any] = [:]
        for (k, v) in props { p[k] = v }
        return ["type": AnyCodable("object"), "properties": AnyCodable(p), "required": AnyCodable(required)]
    }

    private static func str(_ a: [String: Any], _ k: String) -> String { (a[k] as? String) ?? "" }

    // MARK: web_search — DuckDuckGo HTML endpoint (no key) with an optional Brave key.

    static let webSearch = LocalTool(
        spec: ToolSpec(name: "web_search", description: "Search the web. Returns titles, URLs and snippets for the query.",
                       parameters: schema(["query": ["type": "string", "description": "Search query"],
                                           "max_results": ["type": "integer", "description": "1-10, default 6"]], required: ["query"])),
        needsApproval: false,
        describe: { "search: \(str($0, "query"))" },
        run: { args in
            let q = str(args, "query")
            let n = min(max(args["max_results"] as? Int ?? 6, 1), 10)
            guard !q.isEmpty else { return LocalToolResult(text: "query is required", isError: true) }
            if let key = LocalSettings.braveKey, !key.isEmpty {
                var req = URLRequest(url: URL(string: "https://api.search.brave.com/res/v1/web/search?q=\(q.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? q)&count=\(n)")!)
                req.setValue(key, forHTTPHeaderField: "X-Subscription-Token")
                req.setValue("application/json", forHTTPHeaderField: "Accept")
                if let (data, _) = try? await URLSession.shared.data(for: req),
                   let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let results = ((obj["web"] as? [String: Any])?["results"] as? [[String: Any]]) {
                    let lines = results.prefix(n).enumerated().map { i, r in
                        "\(i + 1). \(r["title"] as? String ?? "")\n   \(r["url"] as? String ?? "")\n   \(r["description"] as? String ?? "")"
                    }
                    return LocalToolResult(text: lines.joined(separator: "\n"))
                }
            }
            var req = URLRequest(url: URL(string: "https://html.duckduckgo.com/html/?q=\(q.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? q)")!)
            req.setValue("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Robo/3.0", forHTTPHeaderField: "User-Agent")
            guard let (data, _) = try? await URLSession.shared.data(for: req), let html = String(data: data, encoding: .utf8) else {
                return LocalToolResult(text: "search request failed", isError: true)
            }
            let results = HTMLText.duckDuckGoResults(html).prefix(n)
            if results.isEmpty { return LocalToolResult(text: "No results (or the search page changed). Try web_fetch on a known site.") }
            return LocalToolResult(text: results.enumerated().map { "\($0 + 1). \($1.title)\n   \($1.url)\n   \($1.snippet)" }.joined(separator: "\n"))
        })

    // MARK: web_fetch

    static let webFetch = LocalTool(
        spec: ToolSpec(name: "web_fetch", description: "Fetch a URL and return its readable text (HTML is converted to text; JSON/text returned as-is). Max ~40k characters.",
                       parameters: schema(["url": ["type": "string", "description": "http(s) URL"]], required: ["url"])),
        needsApproval: false,
        describe: { "fetch: \(str($0, "url"))" },
        run: { args in
            guard let url = URL(string: str(args, "url")), ["http", "https"].contains(url.scheme ?? "") else {
                return LocalToolResult(text: "url must be http(s)", isError: true)
            }
            var req = URLRequest(url: url)
            req.setValue("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Robo/3.0", forHTTPHeaderField: "User-Agent")
            req.timeoutInterval = 30
            guard let (data, resp) = try? await URLSession.shared.data(for: req) else { return LocalToolResult(text: "fetch failed", isError: true) }
            let ctype = (resp as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Type") ?? ""
            let body = String(data: data, encoding: .utf8) ?? String(decoding: data, as: UTF8.self)
            let text = ctype.contains("html") ? HTMLText.text(from: body) : body
            return LocalToolResult(text: String(text.prefix(40_000)))
        })

    // MARK: files (app sandbox: Documents/ — visible in the Files app under "Robo")

    private static func sandboxURL(_ rel: String) -> URL? {
        let clean = rel.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: "\\", with: "/")
        guard !clean.hasPrefix("/"), !clean.contains("..") else { return nil }
        return documents.appendingPathComponent(clean.isEmpty ? "." : clean)
    }

    static let listFiles = LocalTool(
        spec: ToolSpec(name: "list_files", description: "List files in Robo's folder (visible in the Files app under Robo). Paths are relative to that folder.",
                       parameters: schema(["path": ["type": "string", "description": "Relative folder, default root"]], required: [])),
        needsApproval: false,
        describe: { "list \(str($0, "path").isEmpty ? "/" : str($0, "path"))" },
        run: { args in
            guard let dir = sandboxURL(str(args, "path")) else { return LocalToolResult(text: "invalid path", isError: true) }
            guard let items = try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.fileSizeKey, .isDirectoryKey]) else {
                return LocalToolResult(text: "folder not found: \(str(args, "path"))", isError: true)
            }
            let lines = items.sorted { $0.lastPathComponent < $1.lastPathComponent }.map { u -> String in
                let v = try? u.resourceValues(forKeys: [.fileSizeKey, .isDirectoryKey])
                return (v?.isDirectory == true ? "[dir]  " : "\(v?.fileSize ?? 0) B  ") + u.lastPathComponent
            }
            return LocalToolResult(text: lines.isEmpty ? "(empty)" : lines.joined(separator: "\n"))
        })

    static let readFile = LocalTool(
        spec: ToolSpec(name: "read_file", description: "Read a text file from Robo's folder.",
                       parameters: schema(["path": ["type": "string"]], required: ["path"])),
        needsApproval: false,
        describe: { "read \(str($0, "path"))" },
        run: { args in
            guard let u = sandboxURL(str(args, "path")), let s = try? String(contentsOf: u, encoding: .utf8) else {
                return LocalToolResult(text: "cannot read \(str(args, "path"))", isError: true)
            }
            return LocalToolResult(text: String(s.prefix(60_000)))
        })

    static let writeFile = LocalTool(
        spec: ToolSpec(name: "write_file", description: "Create or overwrite a text file in Robo's folder (needs the user's approval).",
                       parameters: schema(["path": ["type": "string"], "content": ["type": "string"]], required: ["path", "content"])),
        needsApproval: true,
        describe: { "write \(str($0, "path")) (\(str($0, "content").count) chars)" },
        run: { args in
            guard let u = sandboxURL(str(args, "path")) else { return LocalToolResult(text: "invalid path", isError: true) }
            do {
                try FileManager.default.createDirectory(at: u.deletingLastPathComponent(), withIntermediateDirectories: true)
                try str(args, "content").write(to: u, atomically: true, encoding: .utf8)
                return LocalToolResult(text: "wrote \(str(args, "path"))")
            } catch { return LocalToolResult(text: "write failed: \(error.localizedDescription)", isError: true) }
        })

    // MARK: run_javascript — real code execution via the system JavaScriptCore engine.

    static let runJavaScript = LocalTool(
        spec: ToolSpec(name: "run_javascript", description: "Execute JavaScript (ES2020, no DOM/network) in the built-in engine and return console output and the final value. Use for calculations, data transforms, parsing, prototypes. 10s limit.",
                       parameters: schema(["code": ["type": "string"]], required: ["code"])),
        needsApproval: false,
        describe: { "js: \(str($0, "code").prefix(48))…" },
        run: { args in
            let code = str(args, "code")
            guard let ctx = JSContext() else { return LocalToolResult(text: "JavaScript engine unavailable", isError: true) }
            let log = NSMutableArray()
            let consoleLog: @convention(block) (String) -> Void = { log.add($0) }
            ctx.setObject(["log": consoleLog], forKeyedSubscript: "console" as NSString)
            var errorText: String?
            ctx.exceptionHandler = { _, exc in errorText = exc?.toString() }
            let deadline = Date().addingTimeInterval(10)
            let result = ctx.evaluateScript(code)
            let output = (log as? [String] ?? []).joined(separator: "\n")
            if Date() > deadline { return LocalToolResult(text: output + "\n[timed out]", isError: true) }
            if let e = errorText { return LocalToolResult(text: (output.isEmpty ? "" : output + "\n") + "Error: \(e)", isError: true) }
            let value = result.map { $0.isUndefined ? "" : ($0.toString() ?? "") } ?? ""
            return LocalToolResult(text: [output, value.isEmpty ? "" : "→ \(value)"].filter { !$0.isEmpty }.joined(separator: "\n"))
        })

    // MARK: memory (MEMORY.md / USER.md in the sandbox, same content policy as the desktop/CLI)

    static let memory = LocalTool(
        spec: ToolSpec(name: "memory", description: "Persist a durable fact. target 'memory' = environment/work facts (MEMORY.md); 'user' = facts about the user (USER.md). Secrets, session state, raw output and other people's personal data are refused with guidance.",
                       parameters: schema(["action": ["type": "string", "enum": ["add", "list"]], "target": ["type": "string", "enum": ["memory", "user"]],
                                           "content": ["type": "string"]], required: ["action"])),
        needsApproval: false,
        describe: { "memory \(str($0, "action")) \(str($0, "target"))" },
        run: { args in
            let target = str(args, "target").isEmpty ? "memory" : str(args, "target")
            let file = documents.appendingPathComponent(target == "user" ? "USER.md" : "MEMORY.md")
            if str(args, "action") == "list" {
                return LocalToolResult(text: (try? String(contentsOf: file, encoding: .utf8)) ?? "(empty)")
            }
            let content = str(args, "content")
            let verdict = ContentPolicy.evaluate(target: target, content: content)
            guard verdict.ok else { return LocalToolResult(text: "Not saved: \(verdict.reason). \(verdict.hint)", isError: true) }
            let existing = (try? String(contentsOf: file, encoding: .utf8)) ?? ""
            try? (existing + (existing.isEmpty ? "" : "\n") + "- " + content.replacingOccurrences(of: "\n", with: " ")).write(to: file, atomically: true, encoding: .utf8)
            return LocalToolResult(text: "saved to \(file.lastPathComponent)")
        })

    // MARK: reminders / calendar (EventKit, with permission and approval)

    static let reminders = LocalTool(
        spec: ToolSpec(name: "reminders", description: "List the user's incomplete reminders, or create one (creation needs approval). due is ISO-8601.",
                       parameters: schema(["action": ["type": "string", "enum": ["list", "create"]], "title": ["type": "string"], "due": ["type": "string"], "notes": ["type": "string"]], required: ["action"])),
        needsApproval: true,
        describe: { str($0, "action") == "create" ? "create reminder: \(str($0, "title"))" : "list reminders" },
        run: { args in
            let store = EKEventStore()
            guard (try? await store.requestFullAccessToReminders()) == true else { return LocalToolResult(text: "Reminders permission not granted", isError: true) }
            if str(args, "action") == "create" {
                let r = EKReminder(eventStore: store)
                r.title = str(args, "title"); r.notes = str(args, "notes"); r.calendar = store.defaultCalendarForNewReminders()
                if let due = ISO8601DateFormatter().date(from: str(args, "due")) {
                    r.dueDateComponents = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: due)
                }
                do { try store.save(r, commit: true); return LocalToolResult(text: "created reminder \"\(r.title ?? "")\"") }
                catch { return LocalToolResult(text: error.localizedDescription, isError: true) }
            }
            let pred = store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: nil)
            let items: [EKReminder] = await withCheckedContinuation { c in store.fetchReminders(matching: pred) { c.resume(returning: $0 ?? []) } }
            let f = DateFormatter(); f.dateStyle = .medium; f.timeStyle = .short
            return LocalToolResult(text: items.prefix(50).map { r in
                "• \(r.title ?? "")" + (r.dueDateComponents.flatMap { Calendar.current.date(from: $0) }.map { " — due \(f.string(from: $0))" } ?? "")
            }.joined(separator: "\n").ifEmpty("(no open reminders)"))
        })

    static let calendar = LocalTool(
        spec: ToolSpec(name: "calendar", description: "List events in the next N days, or create an event (creation needs approval). start/end are ISO-8601.",
                       parameters: schema(["action": ["type": "string", "enum": ["list", "create"]], "days": ["type": "integer"], "title": ["type": "string"],
                                           "start": ["type": "string"], "end": ["type": "string"], "location": ["type": "string"]], required: ["action"])),
        needsApproval: true,
        describe: { str($0, "action") == "create" ? "create event: \(str($0, "title"))" : "list calendar" },
        run: { args in
            let store = EKEventStore()
            guard (try? await store.requestFullAccessToEvents()) == true else { return LocalToolResult(text: "Calendar permission not granted", isError: true) }
            let iso = ISO8601DateFormatter()
            if str(args, "action") == "create" {
                guard let s = iso.date(from: str(args, "start")) else { return LocalToolResult(text: "start must be ISO-8601", isError: true) }
                let e = EKEvent(eventStore: store)
                e.title = str(args, "title"); e.startDate = s; e.endDate = iso.date(from: str(args, "end")) ?? s.addingTimeInterval(3600)
                e.location = str(args, "location"); e.calendar = store.defaultCalendarForNewEvents
                do { try store.save(e, span: .thisEvent, commit: true); return LocalToolResult(text: "created event \"\(e.title ?? "")\"") }
                catch { return LocalToolResult(text: error.localizedDescription, isError: true) }
            }
            let days = max(1, min(args["days"] as? Int ?? 7, 60))
            let pred = store.predicateForEvents(withStart: Date(), end: Date().addingTimeInterval(Double(days) * 86400), calendars: nil)
            let f = DateFormatter(); f.dateStyle = .medium; f.timeStyle = .short
            return LocalToolResult(text: store.events(matching: pred).prefix(80).map { "• \(f.string(from: $0.startDate)) — \($0.title ?? "")" }
                .joined(separator: "\n").ifEmpty("(no events in the next \(days) days)"))
        })

    static let currentTime = LocalTool(
        spec: ToolSpec(name: "current_time", description: "Current date, time and time zone on this device.", parameters: schema([:], required: [])),
        needsApproval: false,
        describe: { _ in "time" },
        run: { _ in
            let f = DateFormatter(); f.dateStyle = .full; f.timeStyle = .long
            return LocalToolResult(text: "\(f.string(from: Date())) (\(TimeZone.current.identifier))")
        })
}

// MARK: - Settings shared with tools

public enum LocalSettings {
    public static var braveKey: String? { Keychain.load("brave_key") }
}

// MARK: - Minimal HTML → text

public enum HTMLText {
    public static func text(from html: String) -> String {
        var s = html
        for tag in ["script", "style", "noscript", "svg", "head"] {
            s = s.replacingOccurrences(of: "(?is)<\(tag)[^>]*>.*?</\(tag)>", with: " ", options: .regularExpression)
        }
        s = s.replacingOccurrences(of: "(?i)<br\\s*/?>|</p>|</div>|</li>|</h[1-6]>|</tr>", with: "\n", options: .regularExpression)
        s = s.replacingOccurrences(of: "<[^>]+>", with: " ", options: .regularExpression)
        let entities = ["&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": "\"", "&#39;": "'", "&nbsp;": " ", "&#x27;": "'"]
        for (k, v) in entities { s = s.replacingOccurrences(of: k, with: v) }
        s = s.replacingOccurrences(of: "[ \\t]+", with: " ", options: .regularExpression)
        s = s.replacingOccurrences(of: "\\n\\s*\\n+", with: "\n\n", options: .regularExpression)
        return s.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public struct SearchResult: Equatable { public var title: String; public var url: String; public var snippet: String }

    /// Parse the DuckDuckGo HTML results page (`result__a` links + `result__snippet`).
    public static func duckDuckGoResults(_ html: String) -> [SearchResult] {
        var out: [SearchResult] = []
        let linkRx = try! NSRegularExpression(pattern: "<a[^>]*class=\"result__a\"[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", options: [.dotMatchesLineSeparators])
        let snipRx = try! NSRegularExpression(pattern: "<a[^>]*class=\"result__snippet\"[^>]*>(.*?)</a>|<div[^>]*class=\"result__snippet\"[^>]*>(.*?)</div>", options: [.dotMatchesLineSeparators])
        let ns = html as NSString
        let links = linkRx.matches(in: html, range: NSRange(location: 0, length: ns.length))
        let snips = snipRx.matches(in: html, range: NSRange(location: 0, length: ns.length))
        for (i, m) in links.enumerated() {
            var href = ns.substring(with: m.range(at: 1))
            if let comps = URLComponents(string: href.hasPrefix("//") ? "https:" + href : href),
               let uddg = comps.queryItems?.first(where: { $0.name == "uddg" })?.value { href = uddg }
            let title = text(from: ns.substring(with: m.range(at: 2)))
            var snippet = ""
            if i < snips.count {
                let sm = snips[i]
                let r = sm.range(at: 1).location != NSNotFound ? sm.range(at: 1) : sm.range(at: 2)
                if r.location != NSNotFound { snippet = text(from: ns.substring(with: r)) }
            }
            out.append(SearchResult(title: title, url: href, snippet: snippet))
        }
        return out
    }
}

// MARK: - Content policy (port of agent/content_policy.py, same rules)

public enum ContentPolicy {
    public struct Verdict { public var ok: Bool; public var reason: String; public var hint: String }

    static let secrets: [(String, String)] = [
        ("private key", "-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        ("OpenAI-style key", "\\bsk-(?:proj-|ant-|or-v1-)?[A-Za-z0-9_\\-]{16,}"),
        ("GitHub token", "\\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
        ("AWS access key", "\\bAKIA[0-9A-Z]{16}\\b"),
        ("Google API key", "\\bAIza[0-9A-Za-z_\\-]{30,}"),
        ("Slack token", "\\bxox[abprs]-[A-Za-z0-9\\-]{10,}"),
        ("JWT", "\\beyJ[A-Za-z0-9_\\-]{10,}\\.eyJ[A-Za-z0-9_\\-]{10,}\\.[A-Za-z0-9_\\-]{10,}"),
        ("bearer token", "(?i)\\bbearer\\s+[A-Za-z0-9_\\-\\.=]{20,}"),
        ("password assignment", "(?i)\\b(?:password|passwd|pwd|secret|api[_\\- ]?key|token|client[_\\- ]?secret)\\s*[:=]\\s*['\"]?[^\\s'\"]{6,}"),
    ]
    static let overrides: [(String, String)] = [
        ("approval bypass", "(?i)\\b(?:always|auto|automatically)\\s+(?:approve|allow)\\b|\\bskip\\s+(?:the\\s+)?approval|\\bnever\\s+ask\\s+(?:for\\s+)?(?:permission|approval|confirmation)|\\byolo\\s+mode\\b"),
        ("instruction hijack", "(?i)\\bignore\\s+(?:all\\s+)?(?:previous|prior|above|system)\\s+(?:instructions|rules|prompts?)"),
        ("secrecy from operator", "(?i)\\b(?:do not|don't|never)\\s+(?:tell|show|reveal|mention)\\s+(?:this|it)\\s+to\\s+the\\s+(?:user|operator|owner)"),
    ]
    static let transient: [(String, String)] = [
        ("clock time", "\\b(?:[01]?\\d|2[0-3]):[0-5]\\d(?::[0-5]\\d)?\\s*(?:am|pm|AM|PM|UTC|GMT)?\\b"),
        ("'currently/right now' state", "(?i)\\b(?:right now|currently|at the moment|for now|is running|is still running|in progress|temporarily)\\b"),
    ]

    static func find(_ rules: [(String, String)], _ text: String) -> [String] {
        rules.compactMap { label, pattern in text.range(of: pattern, options: .regularExpression) != nil ? label : nil }
    }

    public static func evaluate(target: String, content: String) -> Verdict {
        let t = content.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty { return Verdict(ok: false, reason: "the entry is empty", hint: "") }
        let s = find(secrets, t)
        if !s.isEmpty { return Verdict(ok: false, reason: "it contains a secret (\(s.joined(separator: ", ")))", hint: "Store where the credential lives, never its value.") }
        let o = find(overrides, t)
        if !o.isEmpty { return Verdict(ok: false, reason: "it would change Robo's safety behaviour (\(o.joined(separator: ", ")))", hint: "Memory records facts and preferences only.") }
        if t.range(of: "(?m)^\\s*Traceback \\(most recent call last\\)", options: .regularExpression) != nil {
            return Verdict(ok: false, reason: "it looks like raw tool output", hint: "Write the conclusion instead.")
        }
        let tr = find(transient, t)
        if !tr.isEmpty { return Verdict(ok: false, reason: "it describes session-bound state (\(tr.joined(separator: ", ")))", hint: "Keep only what is still true next week.") }
        if target == "memory", t.range(of: "\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\b", options: .regularExpression) != nil {
            return Verdict(ok: false, reason: "it contains personal contact data", hint: "Facts about the user go to target 'user'; other people's data should not be stored.")
        }
        if t.count > 600 || t.split(separator: "\n").count > 8 {
            return Verdict(ok: false, reason: "it is too long for one entry", hint: "One durable fact per entry (≤ 600 chars, ≤ 8 lines).")
        }
        return Verdict(ok: true, reason: "", hint: "")
    }
}

extension String {
    func ifEmpty(_ alt: String) -> String { isEmpty ? alt : self }
}
