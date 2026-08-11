import Foundation
import UIKit
import UserNotifications

public final class PushNotificationCoordinator: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    @Published public private(set) var authorizationStatus: UNAuthorizationStatus = .notDetermined
    @Published public private(set) var deviceToken: String?

    public override init() {
        super.init()
        UNUserNotificationCenter.current().delegate = self
    }

    @MainActor
    public func refreshAuthorizationStatus() async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        authorizationStatus = settings.authorizationStatus
    }

    @MainActor
    public func requestPermission() async {
        _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound])
        await refreshAuthorizationStatus()
        UIApplication.shared.registerForRemoteNotifications()
    }

    public func updateDeviceToken(_ data: Data) {
        deviceToken = data.map { String(format: "%02x", $0) }.joined()
    }
}
