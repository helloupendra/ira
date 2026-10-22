import AppKit
import IraKit

// Ira for Mac: a menu-bar app (LSUIElement), so no Dock icon.
//
// Two commands for scripts and support, run without any window:
//   Ira --status          this Mac's pairing: paired, not paired, or a key the Keychain did not hand over
//   Ira --pair <link>     pair with a pairing link (the same exchange as the app's pairing page)
//   Ira --remove          what "Remove Ira from this Mac" does: your Ira forgets this Mac, and
//                         the key and settings here are deleted
let arguments = CommandLine.arguments
if arguments.count >= 2, ["--status", "--pair", "--remove"].contains(arguments[1]) {
    let settings = AppSettings()
    let record = PairingRecord(settings: settings, secrets: KeychainStore())
    if arguments[1] == "--status" {
        switch record.status {
        case .paired: print("paired with \(settings.server) as device \(settings.deviceID.map(String.init) ?? "?")")
        case .unpaired: print("not paired")
        case .keyUnreadable(let code): print("paired with \(settings.server), but the Keychain did not hand over the key (\(code))")
        }
        exit(0)
    }
    if arguments[1] == "--remove" {
        let done = DispatchSemaphore(value: 0)
        Task {
            if let url = Pairing.websocketURL(server: settings.server), let token = KeychainStore().load(SecretAccount.device) {
                let goodbye = DeviceClient(url: url, token: { token }, tools: NoToolsAtAll(), label: settings.deviceLabel)
                _ = await goodbye.sayGoodbye()
            }
            done.signal()
        }
        done.wait()
        record.removeOnPurpose()
        if let domain = Bundle.main.bundleIdentifier { settings.defaults.removePersistentDomain(forName: domain) }
        print("removed: your Ira forgot this Mac, and its key and settings here are deleted")
        exit(0)
    }
    guard arguments.count >= 3 else {
        print("say the pairing link: Ira --pair \"https://ira.example.com/pair#code=ABCD-EFGH\"")
        exit(2)
    }
    let link = arguments[2]
    let done = DispatchSemaphore(value: 0)
    var status: Int32 = 0
    Task {
        do {
            let (server, code) = try Pairing.parse(link, server: settings.server.isEmpty ? nil : settings.server)
            let paired = try await Pairing.exchange(server: server, code: code)
            try record.adopt(server: paired.server, token: paired.token, deviceID: paired.deviceID, label: paired.label)
            print("paired with \(paired.server) as device \(paired.deviceID)")
        } catch {
            print("not paired: \(error.localizedDescription)")
            status = 1
        }
        done.signal()
    }
    done.wait()
    exit(status)
}

struct NoToolsAtAll: ToolRunner {
    var definitions: [JSONValue] { [] }
    func call(_ name: String, args: JSONValue) async throws -> JSONValue { throw ToolFailure("no tools") }
}

MainActor.assumeIsolated {
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.accessory)
    withExtendedLifetime(delegate) {
        app.run()
    }
}
