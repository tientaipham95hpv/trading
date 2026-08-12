import SwiftUI
import TradingControl

@main
struct TradingControlIOSApp: App {
    @UIApplicationDelegateAdaptor(TradingAppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup {
            TradingControlView()
        }
    }
}
