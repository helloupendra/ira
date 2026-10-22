import Foundation

/// Removing this iPhone: `bye` instead of a hello.
extension DeviceClient {
    /// Tell the server this iPhone is being removed: it revokes the token at once.
    /// Sent instead of a hello.
    public func sayGoodbye() async -> Bool {
        do {
            let channel = try await connector.connect(url: url, headers: headers(token()))
            defer { channel.close(code: 1000) }
            try await channel.send(.text(DeviceProtocol.bye.encoded()))
            // The server closes the connection after revoking; wait a moment for that.
            _ = try? await withTimeout(3) { try await channel.receive() }
            return true
        } catch {
            return false
        }
    }
}
