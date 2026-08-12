import Combine
import Foundation
import UIKit
import UserNotifications

extension Notification.Name {
    static let tradingDeviceTokenUpdated = Notification.Name("tradingDeviceTokenUpdated")
}

public final class PushNotificationCoordinator: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    @Published public private(set) var authorizationStatus: UNAuthorizationStatus = .notDetermined
    @Published public private(set) var deviceToken: String?

    public override init() {
        super.init()
        UNUserNotificationCenter.current().delegate = self
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleDeviceTokenNotification(_:)),
            name: .tradingDeviceTokenUpdated,
            object: nil
        )
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
        if let deviceToken {
            Task {
                _ = try? await TradingAPI.shared.registerPushToken(deviceToken)
            }
        }
    }

    @MainActor
    public func sendLocalTestNotification() async {
        let content = UNMutableNotificationContent()
        content.title = "Trading Bot"
        content.body = "Thông báo cục bộ hoạt động. Push thật cần backend APNs gửi token này."
        content.sound = .default
        let request = UNNotificationRequest(
            identifier: "trading-local-test-\(Date().timeIntervalSince1970)",
            content: content,
            trigger: UNTimeIntervalNotificationTrigger(timeInterval: 1, repeats: false)
        )
        try? await UNUserNotificationCenter.current().add(request)
    }

    @objc private func handleDeviceTokenNotification(_ notification: Notification) {
        guard let data = notification.object as? Data else { return }
        Task { @MainActor in
            updateDeviceToken(data)
        }
    }
}

public final class TradingAppDelegate: NSObject, UIApplicationDelegate {
    public func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        NotificationCenter.default.post(name: .tradingDeviceTokenUpdated, object: deviceToken)
    }
}
