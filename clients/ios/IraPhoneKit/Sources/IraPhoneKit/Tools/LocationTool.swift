import CoreLocation
import Foundation

/// `location_now`: where the iPhone is, once, when asked. iOS gives the location
/// to this app only while it is in use; the iPhone keeps nothing, and the
/// answer goes only to the person's own Ira.
public enum LocationTool {
    public static func now(_ raw: JSONValue) async throws -> JSONValue {
        _ = try ToolArgs(raw, allowed: [])
        let fix = try await LocationReader.read(timeout: 12)
        let address = await address(of: fix)
        let accuracy = Int(fix.horizontalAccuracy.rounded())
        let age = max(0, Int(-fix.timestamp.timeIntervalSinceNow))
        var result: [String: JSONValue] = [
            "latitude": .number(rounded(fix.coordinate.latitude)),
            "longitude": .number(rounded(fix.coordinate.longitude)),
            "accuracy_m": .number(Double(accuracy)),
            "age_s": .number(Double(age)),
        ]
        if let address { result["address"] = .string(address) }
        result["summary"] = .string(summary(address: address, latitude: fix.coordinate.latitude,
                                            longitude: fix.coordinate.longitude, accuracy: accuracy))
        return .object(result)
    }

    /// Five decimals: about a metre, all a person needs.
    static func rounded(_ degrees: Double) -> Double {
        (degrees * 100_000).rounded() / 100_000
    }

    static func summary(address: String?, latitude: Double, longitude: Double, accuracy: Int) -> String {
        let place = address ?? String(format: "%.5f, %.5f", latitude, longitude)
        return "\(place) (within \(accuracy) m)"
    }

    /// The street address, when the iPhone can tell (it asks Apple's geocoder).
    static func address(of location: CLLocation) async -> String? {
        guard let mark = try? await CLGeocoder().reverseGeocodeLocation(location).first else { return nil }
        let parts = [mark.name, mark.subLocality, mark.locality, mark.administrativeArea, mark.country]
        var seen: [String] = []
        for part in parts.compactMap({ $0 }) where !part.isEmpty && !seen.contains(part) { seen.append(part) }
        return seen.isEmpty ? nil : seen.joined(separator: ", ")
    }
}

/// One location fix from Core Location, which answers through a delegate on the
/// main thread.
@MainActor
final class LocationReader: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var waiting: CheckedContinuation<CLLocation, Error>?
    private static var reading: Set<LocationReader> = []

    static func read(timeout: Double) async throws -> CLLocation {
        let reader = LocationReader()
        reading.insert(reader)
        defer { reading.remove(reader) }
        return try await reader.read(timeout: timeout)
    }

    private func read(timeout: Double) async throws -> CLLocation {
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        return try await withCheckedThrowingContinuation { continuation in
            waiting = continuation
            manager.requestLocation()
            Task { @MainActor in
                try? await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
                self.finish(.failure(ToolFailure("the iPhone could not find where it is just now. Try again outdoors or with Wi-Fi on")))
            }
        }
    }

    private func finish(_ result: Result<CLLocation, Error>) {
        guard let waiting else { return }
        self.waiting = nil
        manager.stopUpdatingLocation()
        waiting.resume(with: result)
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let last = locations.last else { return }
        Task { @MainActor in self.finish(.success(last)) }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        let code = (error as? CLError)?.code
        let message: String
        switch code {
        case .denied?: message = "Location is off for Ira on the iPhone. Switch it on in the iPhone's Settings, Ira, Location (While Using the App), then ask again"
        case .locationUnknown?: return  // Core Location keeps trying; the timeout ends it
        default: message = "the iPhone could not find where it is just now"
        }
        Task { @MainActor in self.finish(.failure(ToolFailure(message))) }
    }
}
