import AVFAudio
import Contacts
import CoreLocation
import EventKit
import Foundation
import Speech

/// One line of "Get Ira ready".
public enum ChecklistItem: Hashable, Sendable, Identifiable {
    case pair
    case microphone
    case speech
    case skill(Skill)

    public var id: String {
        switch self {
        case .pair: return "pair"
        case .microphone: return "microphone"
        case .speech: return "speech"
        case .skill(let skill): return skill.rawValue
        }
    }

    public static let all: [ChecklistItem] = [.pair, .microphone, .speech] + Skill.allCases.map { .skill($0) }
}

/// What iOS says about one permission.
public enum PermissionState: Equatable, Sendable {
    case allowed
    /// iOS has not asked yet: the app may show its prompt.
    case notAsked
    /// The person said no. iOS never asks again; only Settings can change it.
    case denied
    /// Screen Time or a profile does not allow it.
    case restricted
    /// Some access, not enough (a calendar Ira may add to but not read).
    case partial(String)
}

/// Reads and asks for permissions. The app's own asks only while it is on
/// screen; a tool call in the background is told what to do instead.
public protocol PermissionProvider: Sendable {
    func state(_ item: ChecklistItem) -> PermissionState
    /// Ask iOS (its prompt shows when it still may); returns the state after.
    func request(_ item: ChecklistItem) async -> PermissionState
}

/// iOS's own permission APIs.
public final class SystemPermissions: PermissionProvider, @unchecked Sendable {
    private let eventKit: EventKitTools

    public init(eventKit: EventKitTools) {
        self.eventKit = eventKit
    }

    public func state(_ item: ChecklistItem) -> PermissionState {
        switch item {
        case .pair:
            return .allowed
        case .microphone:
            switch AVAudioApplication.shared.recordPermission {
            case .granted: return .allowed
            case .denied: return .denied
            default: return .notAsked
            }
        case .speech:
            switch SFSpeechRecognizer.authorizationStatus() {
            case .authorized: return .allowed
            case .denied: return .denied
            case .restricted: return .restricted
            default: return .notAsked
            }
        case .skill(let skill):
            return SystemPermissions.state(skill)
        }
    }

    static func state(_ skill: Skill) -> PermissionState {
        switch skill {
        case .contacts:
            let status = CNContactStore.authorizationStatus(for: .contacts)
            switch status {
            case .authorized: return .allowed
            case .denied: return .denied
            case .restricted: return .restricted
            case .notDetermined: return .notAsked
            default:
                // iOS 18's limited access: the contacts the person chose.
                return .allowed
            }
        case .calendar: return eventState(.event)
        case .reminders: return eventState(.reminder)
        case .location:
            switch CLLocationManager().authorizationStatus {
            case .authorizedAlways, .authorizedWhenInUse: return .allowed
            case .denied: return .denied
            case .restricted: return .restricted
            default: return .notAsked
            }
        case .calls:
            return .allowed  // a tel: link needs no permission; the person's tap is it
        }
    }

    static func eventState(_ type: EKEntityType) -> PermissionState {
        switch EKEventStore.authorizationStatus(for: type) {
        case .fullAccess: return .allowed
        case .writeOnly:
            return .partial(type == .event
                ? "Ira may add events but not read them: choose Full Access."
                : "Ira may add reminders but not read them: choose Full Access.")
        case .denied: return .denied
        case .restricted: return .restricted
        case .notDetermined: return .notAsked
        default: return .allowed  // the old "authorized", before iOS 17
        }
    }

    public func request(_ item: ChecklistItem) async -> PermissionState {
        guard state(item) == .notAsked else { return state(item) }
        switch item {
        case .pair, .skill(.calls):
            break
        case .microphone:
            _ = await AVAudioApplication.requestRecordPermission()
        case .speech:
            await withCheckedContinuation { (done: CheckedContinuation<Void, Never>) in
                SFSpeechRecognizer.requestAuthorization { _ in done.resume() }
            }
        case .skill(.contacts):
            _ = try? await CNContactStore().requestAccess(for: .contacts)
        case .skill(.calendar):
            await eventKit.requestFullAccess(.event)
        case .skill(.reminders):
            await eventKit.requestFullAccess(.reminder)
        case .skill(.location):
            await LocationAccess.request()
        }
        return state(item)
    }
}

/// Asking for the location "while using the app": iOS answers through a delegate,
/// on the main thread, to a manager that must stay alive until then.
@MainActor
final class LocationAccess: NSObject, CLLocationManagerDelegate {
    private static var asking: LocationAccess?
    private let manager = CLLocationManager()
    private var done: CheckedContinuation<Void, Never>?

    static func request() async {
        let access = LocationAccess()
        asking = access
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            access.done = continuation
            access.manager.delegate = access
            access.manager.requestWhenInUseAuthorization()
            // iOS shows no prompt to an app off screen: stop waiting after a minute.
            Task { @MainActor in
                try? await Task.sleep(nanoseconds: 60_000_000_000)
                access.finish()
            }
        }
        asking = nil
    }

    private func finish() {
        done?.resume()
        done = nil
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        guard status != .notDetermined else { return }  // the first call comes before the prompt
        Task { @MainActor in self.finish() }
    }
}
