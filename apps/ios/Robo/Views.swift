// Views.swift — Robo iOS
// Screens: Chat (transcript + composer + hold-to-talk), Approval sheet
// (Allow once / Allow this session / Deny — the same barrier as the TUI),
// Pairing (scan the QR from `robo serve --pair` or paste it), Sessions,
// Settings. Visual language matches the desktop's Ignitee theme: navy
// canvas, indigo structure, ember accent from the Ignitee Now flame.

import AVFoundation
import CoreText
import SwiftUI

// MARK: - Design tokens

enum RoboTheme {
    // Ignitee Now brand tokens, sampled from the logo (assets/brand/BRAND.md).
    static let navy = Color(red: 0.039, green: 0.063, blue: 0.188)      // #0A1030
    static let card = Color(red: 0.055, green: 0.078, blue: 0.216)      // #0E1437
    static let indigo = Color(red: 0.557, green: 0.549, blue: 0.878)    // #8E8CE0
    static let ember = Color(red: 0.937, green: 0.541, blue: 0.133)     // #EF8A22 (primary accent)
    static let flame = Color(red: 0.835, green: 0.153, blue: 0.204)     // #D52734 (gradient start)
    static let muted = Color(red: 0.663, green: 0.682, blue: 0.812)     // #A9AECF
    static let snow = Color(red: 1.0, green: 0.914, blue: 0.839)        // #FFE9D6 (warm white)
    static let ok = Color(red: 0.247, green: 0.749, blue: 0.498)        // #3FBF7F
    static let warn = Color(red: 0.949, green: 0.706, blue: 0.255)      // #F2B441
    static let danger = Color(red: 0.941, green: 0.322, blue: 0.373)    // #F0525F

    /// The logo's flame, red to ember. Use for hero marks and primary buttons.
    static let flameGradient = LinearGradient(colors: [flame, Color(red: 0.875, green: 0.353, blue: 0.188), ember],
                                              startPoint: .leading, endPoint: .trailing)

    // MARK: Typography — Poppins (SIL OFL 1.1), bundled in Resources/Fonts.

    /// Brand font for a text style. Scales with Dynamic Type via `relativeTo:`.
    /// If the font failed to register, SwiftUI falls back to the system font.
    static func font(_ style: Font.TextStyle, weight: Font.Weight = .regular) -> Font {
        let face: String
        switch weight {
        case .bold, .heavy, .black: face = "Poppins-Bold"
        case .medium, .semibold: face = "Poppins-Medium"
        default: face = "Poppins-Regular"
        }
        return .custom(face, size: pointSize(style), relativeTo: style)
    }

    private static func pointSize(_ style: Font.TextStyle) -> CGFloat {
        switch style {
        case .largeTitle: return 34
        case .title: return 28
        case .title2: return 22
        case .title3: return 20
        case .headline, .body: return 17
        case .callout: return 16
        case .subheadline: return 15
        case .footnote: return 13
        case .caption: return 12
        case .caption2: return 11
        @unknown default: return 17
        }
    }

    /// Register the bundled fonts once at launch. Looks in both the bundle root
    /// and Resources/Fonts so it works however the project lays resources out.
    static func registerFonts() {
        for face in ["Poppins-Regular", "Poppins-Italic", "Poppins-Medium", "Poppins-Bold"] {
            let url = Bundle.main.url(forResource: face, withExtension: "ttf")
                ?? Bundle.main.url(forResource: face, withExtension: "ttf", subdirectory: "Resources/Fonts")
                ?? Bundle.main.url(forResource: face, withExtension: "ttf", subdirectory: "Fonts")
            if let url { CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil) }
        }
    }
}

// MARK: - Root

public struct RootView: View {
    @EnvironmentObject var app: AppModel

    public init() {}

    public var body: some View {
        Group {
            if !app.configured {
                OnboardingView()
            } else {
                ChatView()
            }
        }
        .preferredColorScheme(.dark)
        .tint(RoboTheme.ember)
        .task { await app.connect() }
    }
}

// MARK: - Chat

struct ChatView: View {
    @EnvironmentObject var app: AppModel
    @State private var draft = ""
    @State private var showSessions = false
    @State private var showSettings = false
    @FocusState private var composerFocused: Bool

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                header
                transcript
                composer
            }
            .background(RoboTheme.navy.ignoresSafeArea())
            .toolbar(.hidden, for: .navigationBar)
            .sheet(isPresented: $showSessions) { SessionsView() }
            .sheet(isPresented: $showSettings) { SettingsView() }
            .sheet(item: $app.approval) { req in ApprovalSheet(request: req) }
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            Rectangle().fill(RoboTheme.ember).frame(width: 3, height: 22)
            VStack(alignment: .leading, spacing: 1) {
                Text("ROBO").font(.system(.subheadline, design: .monospaced).weight(.bold)).foregroundStyle(RoboTheme.snow)
                Text(app.model.isEmpty ? (app.mode == .local ? "local" : (app.client.connected ? "connected" : "connecting…")) : app.model.split(separator: "/").last.map(String.init) ?? app.model)
                    .font(RoboTheme.font(.caption)).foregroundStyle(RoboTheme.muted).lineLimit(1)
            }
            Spacer()
            Text(app.mode == .local ? "on device" : "gateway").font(RoboTheme.font(.caption2)).foregroundStyle(RoboTheme.muted)
            Circle().fill(app.mode == .local ? RoboTheme.ok : (app.client.connected ? RoboTheme.ok : RoboTheme.warn)).frame(width: 8, height: 8)
            Button { showSessions = true } label: { Image(systemName: "clock.arrow.circlepath") }
            Button { showSettings = true } label: { Image(systemName: "gearshape") }
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
        .background(RoboTheme.navy)
        .overlay(alignment: .bottom) { Rectangle().fill(RoboTheme.card).frame(height: 1) }
    }

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if let banner = app.banner {
                        Label(banner, systemImage: "exclamationmark.triangle").font(RoboTheme.font(.footnote)).foregroundStyle(RoboTheme.warn)
                    }
                    if app.items.isEmpty {
                        EmptyStateView()
                    }
                    ForEach(app.items) { item in
                        TranscriptRow(item: item).id(item.id)
                    }
                    if !app.statusLine.isEmpty && app.busy {
                        HStack(spacing: 6) {
                            ProgressView().controlSize(.mini)
                            Text(app.statusLine).font(RoboTheme.font(.caption)).foregroundStyle(RoboTheme.muted)
                        }.padding(.leading, 4)
                    }
                    Color.clear.frame(height: 1).id("bottom")
                }
                .padding(16)
            }
            .onChange(of: app.items.count) { _, _ in withAnimation { proxy.scrollTo("bottom", anchor: .bottom) } }
        }
    }

    private var composer: some View {
        VStack(spacing: 8) {
            if app.voice.listening {
                Text(app.voice.transcript.isEmpty ? "Listening…" : app.voice.transcript)
                    .font(RoboTheme.font(.footnote)).foregroundStyle(RoboTheme.ember).frame(maxWidth: .infinity, alignment: .leading)
            }
            HStack(alignment: .bottom, spacing: 10) {
                TextField("Describe the task — Robo plans, verifies, then acts", text: $draft, axis: .vertical)
                    .lineLimit(1...6)
                    .textFieldStyle(.plain)
                    .padding(10)
                    .background(RoboTheme.card, in: RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(composerFocused ? RoboTheme.ember : RoboTheme.card.opacity(0.6), lineWidth: 1))
                    .focused($composerFocused)
                    .foregroundStyle(RoboTheme.snow)
                    .onSubmit { Task { await sendDraft() } }
                HoldToTalkButton()
                if app.busy {
                    Button { Task { await app.stop() } } label: { Image(systemName: "stop.fill").font(.title3) }
                        .buttonStyle(.borderedProminent).tint(RoboTheme.danger)
                        .accessibilityLabel("Stop Robo")
                } else {
                    Button { Task { await sendDraft() } } label: { Image(systemName: "arrow.up").font(.title3.weight(.bold)) }
                        .buttonStyle(.borderedProminent).tint(RoboTheme.indigo)
                        .disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty || (app.mode == .gateway && !app.client.connected))
                        .accessibilityLabel("Send")
                }
            }
        }
        .padding(12)
        .background(RoboTheme.navy)
    }

    private func sendDraft() async {
        let text = draft
        draft = ""
        await app.send(text)
    }
}

struct EmptyStateView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("What should Robo work on?").font(RoboTheme.font(.title3, weight: .semibold)).foregroundStyle(RoboTheme.snow)
            Text("It runs on your gateway machine — code, files, terminals, browsers. Dangerous commands wait for your approval here.")
                .font(RoboTheme.font(.footnote)).foregroundStyle(RoboTheme.muted)
            VStack(alignment: .leading, spacing: 4) {
                ForEach(["Summarise what changed in the repo this week", "Run the test suite and fix what fails", "Reverse-engineer ./sample.bin and explain main"], id: \.self) { s in
                    Text("›  \(s)").font(.footnote.monospaced()).foregroundStyle(RoboTheme.ember)
                }
            }.padding(.top, 4)
        }
        .padding(.top, 40)
    }
}

struct TranscriptRow: View {
    let item: TranscriptItem
    @State private var expanded = false

    var body: some View {
        switch item {
        case .user(_, let text):
            HStack { Spacer(minLength: 40)
                Text(text).padding(12).background(RoboTheme.card, in: RoundedRectangle(cornerRadius: 14)).foregroundStyle(RoboTheme.snow)
            }
        case .assistant(_, let text, let streaming):
            VStack(alignment: .leading, spacing: 4) {
                if text.isEmpty && streaming {
                    HStack(spacing: 6) { ProgressView().controlSize(.mini); Text("Robo is thinking…").font(RoboTheme.font(.caption)).foregroundStyle(RoboTheme.muted) }
                } else {
                    Text(LocalizedStringKey(text)).foregroundStyle(RoboTheme.snow).textSelection(.enabled)
                }
            }
        case .tools(_, let entries, let running):
            VStack(alignment: .leading, spacing: 6) {
                Button { withAnimation { expanded.toggle() } } label: {
                    HStack(spacing: 6) {
                        Image(systemName: expanded ? "chevron.down" : "chevron.right").font(.caption2)
                        Text("Tool calls (\(entries.count))").font(RoboTheme.font(.caption, weight: .semibold))
                        if running, let last = entries.last { Text("·  \(last.label)").font(RoboTheme.font(.caption)).lineLimit(1) }
                        else if let last = entries.last { Text("·  done").font(RoboTheme.font(.caption)) }
                        Spacer()
                        if running { ProgressView().controlSize(.mini) }
                    }.foregroundStyle(RoboTheme.muted)
                }
                if expanded {
                    ForEach(entries) { e in
                        HStack(spacing: 6) {
                            Image(systemName: e.ok == nil ? "circle.dotted" : (e.ok == true ? "checkmark.circle" : "xmark.circle"))
                                .foregroundStyle(e.ok == false ? RoboTheme.danger : RoboTheme.ember).font(RoboTheme.font(.caption2))
                            Text(e.name).font(.caption.monospaced()).foregroundStyle(RoboTheme.snow)
                            Text(e.label).font(RoboTheme.font(.caption)).foregroundStyle(RoboTheme.muted).lineLimit(1)
                        }.padding(.leading, 14)
                    }
                }
            }
            .padding(10).background(RoboTheme.card.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
        case .status(_, let text):
            Text(text).font(RoboTheme.font(.caption)).foregroundStyle(RoboTheme.muted)
        }
    }
}

// MARK: - Voice

struct HoldToTalkButton: View {
    @EnvironmentObject var app: AppModel
    @State private var permitted = false

    var body: some View {
        Image(systemName: app.voice.listening ? "waveform" : "mic.fill")
            .font(RoboTheme.font(.title3))
            .frame(width: 44, height: 44)
            .background(app.voice.listening ? RoboTheme.ember : RoboTheme.card, in: Circle())
            .foregroundStyle(app.voice.listening ? RoboTheme.navy : RoboTheme.snow)
            .accessibilityLabel("Hold to talk")
            .onLongPressGesture(minimumDuration: 0.15, pressing: { pressing in
                if pressing { Task { await start() } } else { finish() }
            }, perform: {})
    }

    private func start() async {
        if !permitted { permitted = await app.voice.requestPermissions() }
        guard permitted else { app.banner = "Microphone or speech permission was not granted."; return }
        do { try app.voice.startListening() } catch { app.banner = error.localizedDescription }
    }

    private func finish() {
        app.voice.stopListening()
        let text = app.voice.transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        Task { await app.send(text) }
    }
}

// MARK: - Approval

struct ApprovalSheet: View {
    @EnvironmentObject var app: AppModel
    let request: ApprovalRequest

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 8) {
                Rectangle().fill(RoboTheme.warn).frame(width: 3, height: 22)
                Text("ROBO · APPROVAL").font(.system(.subheadline, design: .monospaced).weight(.bold))
            }
            Text("Robo wants to run a command that matched a dangerous pattern. Nothing runs until you answer.")
                .font(RoboTheme.font(.footnote)).foregroundStyle(RoboTheme.muted)
            VStack(alignment: .leading, spacing: 6) {
                Text(request.description).font(RoboTheme.font(.subheadline, weight: .semibold)).foregroundStyle(RoboTheme.warn)
                ScrollView(.horizontal) {
                    Text(request.command).font(.footnote.monospaced()).padding(10)
                }
                .background(RoboTheme.navy, in: RoundedRectangle(cornerRadius: 8))
            }
            VStack(spacing: 10) {
                Button { Task { await app.answerApproval("once") } } label: { Label("Allow once", systemImage: "checkmark").frame(maxWidth: .infinity) }
                    .buttonStyle(.borderedProminent).tint(RoboTheme.indigo)
                Button { Task { await app.answerApproval("session") } } label: { Label("Allow for this session", systemImage: "checkmark.circle").frame(maxWidth: .infinity) }
                    .buttonStyle(.bordered)
                Button(role: .destructive) { Task { await app.answerApproval("deny") } } label: { Label("Deny and stop", systemImage: "xmark").frame(maxWidth: .infinity) }
                    .buttonStyle(.bordered).tint(RoboTheme.danger)
            }
            Text("Deny stops the turn; tell Robo what to do next in the chat.").font(RoboTheme.font(.caption2)).foregroundStyle(RoboTheme.muted)
        }
        .padding(20)
        .presentationDetents([.medium, .large])
        .interactiveDismissDisabled(true)
        .background(RoboTheme.card)
    }
}

// MARK: - Pairing

struct PairingView: View {
    @EnvironmentObject var app: AppModel
    @State private var url = ""
    @State private var token = ""
    @State private var pairing = ""
    @State private var showScanner = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Connect to your Robo").font(RoboTheme.font(.headline))
                        Text("On the machine that runs Robo:\n  robo serve --host 0.0.0.0 --pair\nthen scan the QR code it shows, or paste the pairing string.")
                            .font(.footnote.monospaced()).foregroundStyle(RoboTheme.muted)
                    }
                }
                Section("Pair") {
                    Button { showScanner = true } label: { Label("Scan pairing QR", systemImage: "qrcode.viewfinder") }
                    TextField("robo://pair?url=…&token=…", text: $pairing).textInputAutocapitalization(.never).autocorrectionDisabled()
                    Button("Pair from string") { pairFrom(pairing) }.disabled(pairing.isEmpty)
                }
                Section("Or enter manually") {
                    TextField("Gateway URL (https://host:8642)", text: $url).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                    SecureField("Access token", text: $token)
                    Button("Connect") {
                        guard let u = URL(string: url.trimmingCharacters(in: .whitespaces)), !token.isEmpty else { error = "Enter a valid URL and token."; return }
                        Task { await app.pair(GatewayEndpoint(baseURL: u, accessToken: token)) }
                    }.disabled(url.isEmpty || token.isEmpty)
                }
                if let error { Section { Text(error).foregroundStyle(RoboTheme.danger).font(RoboTheme.font(.footnote)) } }
                Section { Text("Use HTTPS (or a Tailscale/VPN address) for anything outside your home network. The token is stored in the iOS Keychain and only ever sent to the gateway you paired.").font(RoboTheme.font(.caption2)).foregroundStyle(RoboTheme.muted) }
            }
            .navigationTitle("Robo")
            .sheet(isPresented: $showScanner) { QRScannerView { code in showScanner = false; pairFrom(code) } }
        }
    }

    private func pairFrom(_ code: String) {
        guard let ep = GatewayEndpoint.fromPairingString(code) else { error = "That is not a Robo pairing string."; return }
        Task { await app.pair(ep) }
    }
}

struct QRScannerView: UIViewControllerRepresentable {
    let onCode: (String) -> Void

    func makeUIViewController(context: Context) -> ScannerController { ScannerController(onCode: onCode) }
    func updateUIViewController(_ uiViewController: ScannerController, context: Context) {}
}

final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    private let session = AVCaptureSession()
    private let onCode: (String) -> Void
    private var fired = false

    init(onCode: @escaping (String) -> Void) { self.onCode = onCode; super.init(nibName: nil, bundle: nil) }
    required init?(coder: NSCoder) { fatalError("unsupported") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        guard let device = AVCaptureDevice.default(for: .video), let input = try? AVCaptureDeviceInput(device: device) else { return }
        session.addInput(input)
        let output = AVCaptureMetadataOutput()
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]
        let preview = AVCaptureVideoPreviewLayer(session: session)
        preview.videoGravity = .resizeAspectFill
        preview.frame = view.bounds
        view.layer.addSublayer(preview)
        DispatchQueue.global(qos: .userInitiated).async { self.session.startRunning() }
    }

    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard !fired, let obj = objects.first as? AVMetadataMachineReadableCodeObject, let s = obj.stringValue else { return }
        fired = true
        session.stopRunning()
        onCode(s)
    }
}

// MARK: - Sessions & Settings

struct SessionsView: View {
    @EnvironmentObject var app: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Button { Task { await app.newSession(); dismiss() } } label: { Label("New session", systemImage: "plus") }
                ForEach(app.sessions, id: \.id) { s in
                    Button { Task { await app.openSession(s.id); dismiss() } } label: {
                        VStack(alignment: .leading) {
                            Text(s.title.isEmpty ? "Untitled" : s.title).foregroundStyle(RoboTheme.snow)
                            Text(s.id).font(.caption2.monospaced()).foregroundStyle(RoboTheme.muted)
                        }
                    }
                }
            }
            .navigationTitle("Sessions")
            .task { await app.refreshSessions() }
        }
    }
}

struct SettingsView: View {
    @EnvironmentObject var app: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Run mode") {
                    Picker("Robo runs", selection: Binding(get: { app.mode }, set: { app.setMode($0) })) {
                        Text("On this iPhone").tag(RunMode.local)
                        Text("Via a computer (gateway)").tag(RunMode.gateway)
                    }.pickerStyle(.segmented)
                    if app.mode == .local {
                        LabeledContent("Provider", value: app.provider.map { "\($0.kind.label) · \($0.model)" } ?? "not set")
                        NavigationLink("Change provider / API key") { ProviderSetupView() }
                        Text("Robo's files, MEMORY.md and sessions live in the Files app under Robo.").font(RoboTheme.font(.caption2)).foregroundStyle(RoboTheme.muted)
                    }
                }
                Section("Gateway") {
                    LabeledContent("URL", value: app.endpoint?.baseURL.absoluteString ?? "—")
                    LabeledContent("Status", value: app.client.connected ? "connected" : (app.client.lastError ?? "disconnected"))
                    if app.endpoint == nil { NavigationLink("Pair with a computer") { PairingView() } }
                    Button("Reconnect") { Task { await app.connect() } }
                    Button("Unpair", role: .destructive) { app.unpair(); dismiss() }
                }
                Section("Voice") {
                    Toggle("Speak replies aloud", isOn: $app.voice.speakReplies)
                    Text("Hold the microphone button to talk. Recognition runs on-device when your iPhone supports it.").font(RoboTheme.font(.caption2)).foregroundStyle(RoboTheme.muted)
                }
                Section("About") {
                    LabeledContent("Robo", value: "3.0.1")
                    Text("An Ignitee Now product. Robo runs on your own machine; this app is a remote control and voice front end.").font(RoboTheme.font(.caption2)).foregroundStyle(RoboTheme.muted)
                }
            }
            .navigationTitle("Settings")
        }
    }
}


// MARK: - Onboarding: choose how Robo runs

struct OnboardingView: View {
    @EnvironmentObject var app: AppModel
    @State private var showPairing = false
    @State private var showProvider = false

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 20) {
                HStack(spacing: 10) {
                    Rectangle().fill(RoboTheme.ember).frame(width: 4, height: 34)
                    VStack(alignment: .leading) {
                        Text("ROBO").font(.system(.title2, design: .monospaced).weight(.bold)).foregroundStyle(RoboTheme.snow)
                        Text("autonomous engineering agent · Ignitee Now").font(RoboTheme.font(.caption)).foregroundStyle(RoboTheme.muted)
                    }
                }
                Text("Choose how Robo runs. You can switch any time in Settings.").font(RoboTheme.font(.footnote)).foregroundStyle(RoboTheme.muted)

                ModeCard(title: "On this iPhone", badge: "Bring your API key",
                         text: "Robo thinks and works on the phone: web research, files in its own folder, real JavaScript execution, memory, reminders and calendar. Same brain, same rules, no computer needed.",
                         action: { showProvider = true })
                ModeCard(title: "Connect to a computer", badge: "Full power",
                         text: "Pair with Robo running on your Mac, Linux box or server (`robo serve --pair`) for terminals, code, repos, browsers and everything else. The phone controls it and answers approvals.",
                         action: { showPairing = true })
                Spacer()
            }
            .padding(20)
            .background(RoboTheme.navy.ignoresSafeArea())
            .sheet(isPresented: $showProvider) { ProviderSetupView() }
            .sheet(isPresented: $showPairing) { PairingView() }
        }
        .preferredColorScheme(.dark)
    }
}

struct ModeCard: View {
    let title: String; let badge: String; let text: String; let action: () -> Void
    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(title).font(RoboTheme.font(.headline)).foregroundStyle(RoboTheme.snow)
                    Spacer()
                    Text(badge).font(RoboTheme.font(.caption2, weight: .semibold)).padding(.horizontal, 8).padding(.vertical, 3)
                        .background(RoboTheme.ember.opacity(0.18), in: Capsule()).foregroundStyle(RoboTheme.ember)
                }
                Text(text).font(RoboTheme.font(.footnote)).foregroundStyle(RoboTheme.muted).multilineTextAlignment(.leading)
            }
            .padding(14)
            .background(RoboTheme.card, in: RoundedRectangle(cornerRadius: 14))
        }
        .buttonStyle(.plain)
    }
}

struct ProviderSetupView: View {
    @EnvironmentObject var app: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var kind: ProviderKind = .openrouter
    @State private var model = ProviderKind.openrouter.defaultModel
    @State private var baseURL = ProviderKind.openrouter.defaultBaseURL
    @State private var apiKey = ""
    @State private var braveKey = ""
    @State private var effort = "high"

    var body: some View {
        NavigationStack {
            Form {
                Section("Provider") {
                    Picker("Provider", selection: $kind) { ForEach(ProviderKind.allCases, id: \.self) { Text($0.label).tag($0) } }
                        .onChange(of: kind) { _, k in model = k.defaultModel; baseURL = k.defaultBaseURL }
                    TextField("Model", text: $model).textInputAutocapitalization(.never).autocorrectionDisabled()
                    SecureField(kind == .custom ? "API key (optional)" : "API key", text: $apiKey)
                    if kind == .custom { TextField("Base URL (OpenAI-compatible)", text: $baseURL).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled() }
                }
                Section("Thinking") {
                    Picker("Reasoning effort", selection: $effort) { ForEach(["none", "low", "medium", "high", "xhigh"], id: \.self) { Text($0) } }
                    Text("Deep thinking is Robo's default posture: plan, verify, then act. Lower it only for cheap throwaway chats.").font(RoboTheme.font(.caption2)).foregroundStyle(RoboTheme.muted)
                }
                Section("Web search (optional)") {
                    SecureField("Brave Search API key", text: $braveKey)
                    Text("Without a key Robo uses DuckDuckGo's HTML results.").font(RoboTheme.font(.caption2)).foregroundStyle(RoboTheme.muted)
                }
                Section {
                    Button("Start Robo on this iPhone") {
                        var cfg = ProviderConfig(kind: kind, baseURL: baseURL, model: model, apiKey: apiKey)
                        cfg.reasoningEffort = effort
                        if !braveKey.isEmpty { Keychain.save(braveKey, for: "brave_key") }
                        app.configureLocal(cfg)
                        dismiss()
                    }.disabled(model.isEmpty || (apiKey.isEmpty && kind != .custom))
                }
                Section { Text("Keys are stored in the iOS Keychain and sent only to the provider you chose. Requests go directly from your phone to that provider — Ignitee Now runs no relay.").font(RoboTheme.font(.caption2)).foregroundStyle(RoboTheme.muted) }
            }
            .navigationTitle("Robo · On device")
        }
    }
}
