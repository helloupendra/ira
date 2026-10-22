import Foundation

/// Waiting between tries.
extension DeviceClient {
    /// Sleep, unless `reconnectNow` or `stop` comes first: either cancels the sleep.
    func pause(_ seconds: Double) async {
        let nanoseconds = UInt64(max(seconds, 0) * 1_000_000_000)
        let sleeper = Task<Void, Never> {
            try? await Task.sleep(nanoseconds: nanoseconds)
        }
        if !keep(sleeper) { sleeper.cancel() }
        await sleeper.value
        forget(sleeper)
    }

    /// Hold on to the sleep so it can be cut short; false once stopped.
    private func keep(_ sleeper: Task<Void, Never>) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        if stopped { return false }
        self.sleeper = sleeper
        return true
    }

    private func forget(_ sleeper: Task<Void, Never>) {
        lock.lock()
        defer { lock.unlock() }
        if self.sleeper == sleeper { self.sleeper = nil }
    }
}
