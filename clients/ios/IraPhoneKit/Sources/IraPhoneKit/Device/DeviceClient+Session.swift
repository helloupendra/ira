import Foundation

/// A welcomed connection: calls, pings and skills until it closes.
extension DeviceClient {
    func session(channel: WebSocketChannel, sender: FrameSender, deviceID: Int?) async -> WebSocketClosed? {
        let ping = timing.ping
        let pinger = Task {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(ping * 1_000_000_000))
                if Task.isCancelled { return }
                try? await sender.send(DeviceProtocol.ping.encoded())
            }
        }
        var calls: [Task<Void, Never>] = []
        defer {
            pinger.cancel()
            calls.forEach { $0.cancel() }
        }
        while !isStopped {
            let message: WebSocketMessage
            do {
                message = try await withTimeout(timing.silence) { try await channel.receive() }
            } catch is TimedOut {
                log.warning(String(format: "heard nothing for %.0fs; reconnecting", timing.silence))
                return WebSocketClosed(reason: "the server went quiet")
            } catch {
                let closed = error as? WebSocketClosed ?? WebSocketClosed(reason: "the connection ended")
                log.info("connection ended: \(closed.code.map(String.init) ?? "") \(closed.reason)")
                return closed
            }
            guard case .text(let text) = message, let frame = try? DeviceProtocol.decode(text) else {
                continue  // a binary or broken frame: ignored
            }
            switch frame {
            case .call(let id, let tool, let args):
                calls.removeAll { $0.isCancelled }
                let tools = self.tools
                let log = self.log
                calls.append(Task {
                    // Every call is logged: its tool, how long, and how it ended. Never contents.
                    let started = Date()
                    let reply: JSONValue
                    var outcome = "ok"
                    do {
                        let content = try await tools.call(tool, args: args)
                        reply = DeviceProtocol.result(id: id, content: content)
                    } catch let failure as ToolFailure {
                        outcome = "failed"
                        reply = DeviceProtocol.failure(id: id, error: failure.message)
                    } catch {
                        outcome = "failed (\(type(of: error)))"
                        reply = DeviceProtocol.failure(id: id, error: error.localizedDescription)
                    }
                    log.info(String(format: "call %@ %@ in %.2fs", tool, outcome, Date().timeIntervalSince(started)))
                    do {
                        try await sender.send(DeviceProtocol.encodeResult(reply))
                    } catch {
                        log.warning("call \(tool): the answer could not be sent (the connection ended)")
                    }
                })
            case .ping:
                try? await sender.send(DeviceProtocol.pong.encoded())
            case .skills(let now):
                log.info("skills now \(now)")
                onState(.connected(deviceID: deviceID, skills: now))
            case .error(let reason):
                log.warning("the server said: \(reason)")
            case .welcome, .pong, .other:
                break
            }
        }
        return nil
    }
}
