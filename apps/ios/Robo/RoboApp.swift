// RoboApp.swift — Robo iOS entry point (Ignitee Now)
import SwiftUI

@main
struct RoboApp: App {
    @StateObject private var model = AppModel()

    init() { RoboTheme.registerFonts() }

    var body: some Scene {
        WindowGroup {
            RootView().environmentObject(model)
        }
    }
}
