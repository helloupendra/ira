import Foundation

/// Reconnecting: growing delays, and a long wait after the token was refused.
extension DeviceClient {
    func runForever() async {
        var attempt = 0
        while !isStopped {
            guard let token = token() else {
                log.warning("this iPhone's key could not be read from the Keychain; trying again later")
                onState(.keyUnavailable)
                await pause(timing.refusedWait)
                continue
            }
            onState(.connecting)
            let started = Date()
            let closed = await runOnce(token: token)
            if isStopped { return }
            if closed?.unauthorized == true {
                log.warning("the server refused this iPhone's token: it was removed or never paired")
                onState(.refused)
                await pause(timing.refusedWait)
                attempt = 0
                continue
            }
            if Date().timeIntervalSince(started) >= timing.stable {
                attempt = 0
            }
            var delay = timing.backoff[min(attempt, timing.backoff.count - 1)]
            attempt += 1
            if timing.jitter { delay *= Double.random(in: 0.8...1.2) }
            log.info(String(format: "reconnecting in %.0fs", delay))
            onState(.waiting(seconds: delay, reason: closed?.reason ?? "the connection ended"))
            await pause(delay)
        }
    }
}
