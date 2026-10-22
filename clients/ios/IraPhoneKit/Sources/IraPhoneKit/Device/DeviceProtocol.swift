import Foundation

/// The device WebSocket's frames (docs/devices.md): JSON text objects told apart by `type`.
///
/// * this iPhone -> server: `hello`, `result`, `ping`, `pong`, `bye`;
/// * server -> this iPhone: `welcome`, `call`, `ping`, `pong`, `skills`, `error`, and
///   `event`, which this app does not use.
public enum DeviceProtocol {
    public static let maxFrameBytes = 1024 * 1024
    public static let pingSeconds: Double = 30
    public static let silenceSeconds: Double = 90
    public static let path = "/v1/devices/ws"

    /// A frame from the server, checked.
    public enum Incoming: Equatable, Sendable {
        case welcome(deviceID: Int?, label: String?, skills: [String], assistant: String?, wakePhrase: String? = nil)
        case call(id: String, tool: String, args: JSONValue)
        case ping
        case pong
        case skills([String])
        case error(String)
        /// A frame of a type this version does not know: ignored.
        case other(String)
    }

    public struct BadFrame: Error, Equatable {
        public let reason: String
    }

    /// One frame: at most 1 MB of JSON holding an object with a string `type`.
    public static func decode(_ text: String) throws -> Incoming {
        if text.utf8.count > maxFrameBytes {
            throw BadFrame(reason: "frames are 1 MB at most")
        }
        guard let frame = JSONValue.parse(text), frame.objectValue != nil else {
            throw BadFrame(reason: "a frame must be a JSON object")
        }
        guard let type = frame["type"]?.stringValue else {
            throw BadFrame(reason: "a frame must have a \"type\"")
        }
        switch type {
        case "welcome":
            return .welcome(
                deviceID: frame["deviceId"]?.intValue,
                label: frame["label"]?.stringValue,
                skills: strings(frame["skills"]),
                assistant: frame["assistant"]?.stringValue,
                wakePhrase: frame["wakePhrase"]?.stringValue)
        case "call":
            guard let id = frame["id"]?.stringValue, !id.isEmpty else {
                throw BadFrame(reason: "a call needs an id")
            }
            guard let tool = frame["tool"]?.stringValue else {
                throw BadFrame(reason: "a call needs a tool")
            }
            let args = frame["args"] ?? .object([:])
            return .call(id: id, tool: tool, args: args.isNull ? .object([:]) : args)
        case "ping": return .ping
        case "pong": return .pong
        case "skills": return .skills(strings(frame["skills"]))
        case "error": return .error(String((frame["error"]?.stringValue ?? "").prefix(200)))
        default: return .other(String(type.prefix(40)))
        }
    }

    private static func strings(_ value: JSONValue?) -> [String] {
        (value?.arrayValue ?? []).compactMap(\.stringValue)
    }

    public static func hello(label: String, tools: [JSONValue]) -> JSONValue {
        [
            "type": "hello",
            "kind": .string(IraPhone.deviceKind),
            "label": .string(label),
            "version": .string(IraPhone.version),
            "tools": .array(tools),
        ]
    }

    public static func result(id: String, content: JSONValue) -> JSONValue {
        ["type": "result", "id": .string(id), "ok": true, "content": content]
    }

    public static func failure(id: String, error: String) -> JSONValue {
        ["type": "result", "id": .string(id), "ok": false, "error": .string(String(error.prefix(300)))]
    }

    public static let ping: JSONValue = ["type": "ping"]
    public static let pong: JSONValue = ["type": "pong"]
    /// Sent instead of a hello when this iPhone is removed: the server revokes its token.
    public static let bye: JSONValue = ["type": "bye"]

    /// A result as text, replaced by an error when it would be over the 1 MB frame limit.
    public static func encodeResult(_ frame: JSONValue) -> String {
        let text = frame.encoded()
        if text.utf8.count <= maxFrameBytes { return text }
        let id = frame["id"]?.stringValue ?? ""
        return failure(id: id, error: "the answer was larger than 1 MB").encoded()
    }
}
