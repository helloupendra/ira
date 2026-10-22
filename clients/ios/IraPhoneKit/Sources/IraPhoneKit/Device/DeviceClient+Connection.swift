import Foundation

/// One connection: hello, welcome, then the session.
extension DeviceClient {
    /// One connection, from hello until it closes. Returns how it closed, if known.
    public func runOnce(token: String) async -> WebSocketClosed? {
        let channel: WebSocketChannel
        do {
            channel = try await connector.connect(url: url, headers: headers(token))
        } catch {
            let closed = error as? WebSocketClosed ?? WebSocketClosed(reason: Pairing.reason(error))
            log.warning("could not connect: \(closed.reason)")
            return closed
        }
        lock.withLock { current = channel }
        defer {
            lock.withLock { current = nil }
            channel.close(code: 1000)
        }
        let sender = FrameSender(channel: channel)
        do {
            try await sender.send(DeviceProtocol.hello(label: label, tools: tools.definitions).encoded())
            let first = try await withTimeout(timing.silence) { try await channel.receive() }
            guard case .text(let text) = first,
                case .welcome(let deviceID, _, let skills, _, _) = try DeviceProtocol.decode(text)
            else {
                if case .text(let text) = first, case .error(let reason)? = try? DeviceProtocol.decode(text) {
                    log.warning("the server refused the hello: \(reason)")
                    return WebSocketClosed(code: 4400, reason: "the server refused the hello: \(reason)")
                }
                log.warning("the server did not welcome this iPhone")
                return WebSocketClosed(reason: "the server did not welcome this iPhone")
            }
            log.info("connected as device \(deviceID.map(String.init) ?? "?") with skills \(skills)")
            onState(.connected(deviceID: deviceID, skills: skills))
            return await session(channel: channel, sender: sender, deviceID: deviceID)
        } catch {
            let closed = error as? WebSocketClosed ?? WebSocketClosed(reason: "the connection ended")
            log.info("connection ended: \(closed.code.map(String.init) ?? "") \(closed.reason)")
            return closed
        }
    }
}
