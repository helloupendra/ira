import Foundation

/// Running another program: `osascript`, `shortcuts`, `git`, a coding agent.
///
/// Programs start in a process group of their own, so stopping one also
/// stops whatever it started.
public final class Command: @unchecked Sendable {
    public struct Result: Sendable {
        public let status: Int32
        public let stdout: String
        public let stderr: String
        public let timedOut: Bool

        public init(status: Int32, stdout: String, stderr: String = "", timedOut: Bool = false) {
            self.status = status
            self.stdout = stdout
            self.stderr = stderr
            self.timedOut = timedOut
        }
    }

    public let pid: pid_t
    public let stdout: FileHandle
    public let stderr: FileHandle
    private let lock = NSLock()
    private var exitStatus: Int32?

    private init(pid: pid_t, stdout: FileHandle, stderr: FileHandle) {
        self.pid = pid
        self.stdout = stdout
        self.stderr = stderr
    }

    /// Start `argv` in `directory`, with `environment`, and `input` on its stdin.
    public static func start(
        _ argv: [String], directory: String? = nil, environment: [String: String]? = nil, input: String? = nil
    ) throws -> Command {
        guard let program = argv.first else { throw ToolFailure("nothing to run") }
        var actions: posix_spawn_file_actions_t?
        posix_spawn_file_actions_init(&actions)
        defer { posix_spawn_file_actions_destroy(&actions) }
        var attributes: posix_spawnattr_t?
        posix_spawnattr_init(&attributes)
        defer { posix_spawnattr_destroy(&attributes) }
        // A process group of its own (pgid = its pid), so it can be stopped whole.
        posix_spawnattr_setflags(&attributes, Int16(POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_CLOEXEC_DEFAULT))
        posix_spawnattr_setpgroup(&attributes, 0)

        let stdin = Pipe(), out = Pipe(), err = Pipe()
        posix_spawn_file_actions_adddup2(&actions, stdin.fileHandleForReading.fileDescriptor, 0)
        posix_spawn_file_actions_adddup2(&actions, out.fileHandleForWriting.fileDescriptor, 1)
        posix_spawn_file_actions_adddup2(&actions, err.fileHandleForWriting.fileDescriptor, 2)
        if let directory {
            posix_spawn_file_actions_addchdir_np(&actions, directory)
        }

        let env = (environment ?? ProcessInfo.processInfo.environment).map { "\($0.key)=\($0.value)" }
        var pid: pid_t = 0
        let status = withCStrings(argv) { argvPointers in
            withCStrings(env) { envPointers in
                posix_spawnp(&pid, program, &actions, &attributes, argvPointers, envPointers)
            }
        }
        try? stdin.fileHandleForReading.close()
        try? out.fileHandleForWriting.close()
        try? err.fileHandleForWriting.close()
        guard status == 0 else {
            throw ToolFailure("could not start \((program as NSString).lastPathComponent): \(String(cString: strerror(status)))")
        }
        let writer = stdin.fileHandleForWriting
        if let input {
            DispatchQueue.global().async {
                try? writer.write(contentsOf: Data(input.utf8))
                try? writer.close()
            }
        } else {
            try? writer.close()
        }
        return Command(pid: pid, stdout: out.fileHandleForReading, stderr: err.fileHandleForReading)
    }

    /// Wait for the program to end; its exit status (128 + signal when killed).
    public func wait() async -> Int32 {
        if let status = lock.locked({ exitStatus }) { return status }
        let pid = self.pid
        let status: Int32 = await withCheckedContinuation { continuation in
            DispatchQueue.global().async {
                var raw: Int32 = 0
                while waitpid(pid, &raw, 0) == -1 && errno == EINTR {}
                let code = (raw & 0x7f) == 0 ? (raw >> 8) & 0xff : 128 + (raw & 0x7f)
                continuation.resume(returning: code)
            }
        }
        lock.locked { exitStatus = status }
        return status
    }

    /// Stop the program and everything it started.
    public func stop(_ signal: Int32 = SIGTERM) {
        if lock.locked({ exitStatus }) == nil {
            kill(-pid, signal)
        }
    }

    /// Run to the end and collect the output, stopping it after `timeout` seconds.
    public static func run(
        _ argv: [String], directory: String? = nil, environment: [String: String]? = nil, input: String? = nil,
        timeout: Double = 30, maxOutput: Int = 4 * 1024 * 1024
    ) async throws -> Result {
        let command = try start(argv, directory: directory, environment: environment, input: input)
        let expired = Flag()
        let timer = Task {
            try await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
            expired.set()
            command.stop()
            try await Task.sleep(nanoseconds: 2_000_000_000)
            command.stop(SIGKILL)
        }
        async let out = Command.readAll(command.stdout, limit: maxOutput)
        async let err = Command.readAll(command.stderr, limit: 64 * 1024)
        let status = await command.wait()
        timer.cancel()
        let timedOut = expired.value
        let (stdout, stderr) = await (out, err)
        return Result(status: status, stdout: stdout, stderr: stderr, timedOut: timedOut)
    }

    static func readAll(_ handle: FileHandle, limit: Int) async -> String {
        await withCheckedContinuation { continuation in
            DispatchQueue.global().async {
                var data = Data()
                while true {
                    let chunk = handle.availableData
                    if chunk.isEmpty { break }
                    if data.count < limit { data.append(chunk.prefix(limit - data.count)) }
                }
                continuation.resume(returning: String(decoding: data, as: UTF8.self))
            }
        }
    }

    /// Lines as they come, for a program that reports progress.
    public static func lines(_ handle: FileHandle) -> AsyncStream<String> {
        AsyncStream { continuation in
            DispatchQueue.global().async {
                var buffer = Data()
                while true {
                    let chunk = handle.availableData
                    if chunk.isEmpty { break }
                    buffer.append(chunk)
                    while let newline = buffer.firstIndex(of: 0x0A) {
                        let line = buffer[buffer.startIndex..<newline]
                        continuation.yield(String(decoding: line, as: UTF8.self))
                        buffer.removeSubrange(buffer.startIndex...newline)
                    }
                    if buffer.count > 1_000_000 { buffer.removeAll() }  // a runaway line
                }
                if !buffer.isEmpty { continuation.yield(String(decoding: buffer, as: UTF8.self)) }
                continuation.finish()
            }
        }
    }
}

final class Flag: @unchecked Sendable {
    private let lock = NSLock()
    private var raised = false
    func set() { lock.locked { raised = true } }
    var value: Bool { lock.locked { raised } }
}

private func withCStrings<R>(_ strings: [String], _ body: (UnsafeMutablePointer<UnsafeMutablePointer<CChar>?>) -> R) -> R {
    var pointers: [UnsafeMutablePointer<CChar>?] = strings.map { strdup($0) }
    pointers.append(nil)
    defer { pointers.forEach { free($0) } }
    return pointers.withUnsafeMutableBufferPointer { body($0.baseAddress!) }
}
