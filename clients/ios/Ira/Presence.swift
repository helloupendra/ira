import SwiftUI
#if canImport(UIKit)
import UIKit
#else
import AppKit
#endif

/// Ira's look, "Presence", as on the web, the Mac and Android: calm, with one hero object,
/// the lens. Colours come from these tokens only, each with its dark and light value.
enum Presence {
    static let bg = dynamic(dark: 0x0B0D0C, light: 0xF4F2ED)
    static let ink = dynamic(dark: 0xEEF2EF, light: 0x1B1F1D)
    static let muted = dynamic(dark: 0x8B958F, light: 0x6D736F)
    static let faint = dynamic(dark: 0x5A635E, light: 0xA5A79F)
    static let line = dynamic(dark: (0xFFFFFF, 0.07), light: (0x000000, 0.08))
    static let card = dynamic(dark: (0xFFFFFF, 0.035), light: (0xFFFFFF, 0.6))
    /// The ask pill and the person's own turns.
    static let raised = dynamic(dark: (0xFFFFFF, 0.06), light: (0xFFFFFF, 0.85))
    static let green = dynamic(dark: 0x3FBF98, light: 0x1F6F5C)
    static let greenDeep = Color(hex: 0x1F6F5C)
    static let warn = dynamic(dark: 0xE7B65C, light: 0x9A6512)
    static let down = dynamic(dark: 0xF07A6B, light: 0xB3412F)

    /// The serif, for the greeting and the call's words only (New York).
    static func serif(_ size: CGFloat) -> Font { .system(size: size, weight: .regular, design: .serif) }
    static let body = Font.system(size: 16)
    static let secondary = Font.system(size: 14)
    static let label = Font.system(size: 11, weight: .medium)
    static let mono = Font.system(size: 11, design: .monospaced)

    /// "system" (as the iPhone is set), "light" or "dark".
    static func scheme(_ look: String) -> ColorScheme? {
        switch look {
        case "light": return .light
        case "dark": return .dark
        default: return nil
        }
    }

    private static func dynamic(dark: UInt32, light: UInt32) -> Color {
        dynamic(dark: (dark, 1), light: (light, 1))
    }

    private static func dynamic(dark: (UInt32, Double), light: (UInt32, Double)) -> Color {
        #if canImport(UIKit)
        Color(uiColor: UIColor { traits in
            let (hex, alpha) = traits.userInterfaceStyle == .dark ? dark : light
            return UIColor(hex: hex, alpha: alpha)
        })
        #else
        Color(nsColor: NSColor(name: nil) { appearance in
            let (hex, alpha) = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
            return NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                           blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
        })
        #endif
    }
}

#if canImport(UIKit)
extension UIColor {
    convenience init(hex: UInt32, alpha: Double = 1) {
        self.init(
            red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
    }
}
#endif

extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255, opacity: opacity)
    }
}

/// The lens: a small glass sphere with Ira's four bars of light inside. Large in a call (its
/// bars follow the voice), small above the greeting, 26 pt beside each answer.
struct Lens: View {
    var size: CGFloat
    /// The voice level, 0 to about 0.1 (the microphone's RMS); the bars follow it.
    var level: Float = 0
    var breathing = false
    /// While listening: a pulse every 1.2 s and a ring that spreads and fades, even in
    /// silence, so the person always sees Ira is on. A slow fade instead with Reduce Motion.
    var heartbeat = false
    /// While Ira works on an answer: the bars ripple one after another, a slow wave.
    var thinking = false
    /// Hairline rings around it: one at rest, two in a call, none as an avatar.
    var rings = 0
    /// The ring's colour: green, or the warning colour when the microphone gives nothing.
    var tint: Color = Presence.green
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorScheme) private var scheme

    private static let bars: [CGFloat] = [0.17, 0.33, 0.42, 0.25]

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !breathing && !heartbeat && !thinking && level <= 0)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            let beat = Lens.beat(t)
            let breathe =
                reduceMotion ? 1
                : heartbeat ? 1 + 0.04 * beat
                : breathing ? 1 + 0.01 * (1 - cos(t * .pi / 2)) : 1
            ZStack {
                if heartbeat && !reduceMotion {
                    let spread = Lens.spread(t)
                    Circle()
                        .stroke(tint.opacity(0.45 * (1 - spread)), lineWidth: 1.5)
                        .frame(width: size * (1 + 0.5 * spread), height: size * (1 + 0.5 * spread))
                }
                ForEach(0..<rings, id: \.self) { ring in
                    Circle()
                        .stroke(Presence.line, lineWidth: 1)
                        .frame(width: size + CGFloat(ring + 1) * size * 0.22, height: size + CGFloat(ring + 1) * size * 0.22)
                }
                sphere
                HStack(spacing: size * 0.04) {
                    ForEach(Array(Lens.bars.enumerated()), id: \.offset) { index, base in
                        Capsule()
                            .fill(LinearGradient(
                                colors: [Color(hex: 0xD9FFF1), Color(hex: 0x7EE8C4)], startPoint: .top, endPoint: .bottom))
                            .frame(width: max(2, size * 0.038), height: size * base * lift(index, t))
                            .shadow(color: Color(hex: 0x3FBF98, opacity: 0.6), radius: size * 0.03)
                    }
                }
            }
            .scaleEffect(breathe)
            .opacity(heartbeat && reduceMotion ? 1 - 0.25 * beat : 1)
        }
        .frame(width: size + CGFloat(rings) * size * 0.22, height: size + CGFloat(rings) * size * 0.22)
        .accessibilityHidden(true)
    }

    /// The beat, every 1.2 s: 0 at rest, up to 1 and back, smoothly.
    static func beat(_ t: TimeInterval) -> CGFloat {
        CGFloat(0.5 - 0.5 * cos(2 * .pi * t / 1.2))
    }

    /// How far the beat's ring has spread, 0 to 1, starting again every 1.2 s.
    static func spread(_ t: TimeInterval) -> CGFloat {
        CGFloat(t.truncatingRemainder(dividingBy: 1.2) / 1.2)
    }

    private var sphere: some View {
        Circle()
            .fill(RadialGradient(
                colors: [Color(hex: 0x1C5F4F), Color(hex: 0x0F3A30), Color(hex: 0x08201B)],
                center: UnitPoint(x: 0.5, y: 0.38), startRadius: 0, endRadius: size * 0.62))
            .overlay(Circle().fill(RadialGradient(
                colors: [Color.white.opacity(0.22), .clear],
                center: UnitPoint(x: 0.35, y: 0.28), startRadius: 0, endRadius: size * 0.42)))
            .overlay(Circle().strokeBorder(
                LinearGradient(colors: [Color.white.opacity(0.18), .clear], startPoint: .top, endPoint: .center),
                lineWidth: max(1, size / 96)))
            .overlay(Circle().fill(LinearGradient(colors: [.clear, Color.black.opacity(0.28)], startPoint: .center, endPoint: .bottom)))
            .frame(width: size, height: size)
            .shadow(
                color: Color(hex: 0x1F6F5C, opacity: scheme == .dark ? 0.55 : 0.3),
                radius: size * 0.23, y: size * 0.16)
    }

    /// How tall a bar stands now: as drawn at rest, taller with the voice, or rippling while
    /// Ira works (bar after bar, every 1.6 s).
    private func lift(_ index: Int, _ t: TimeInterval) -> CGFloat {
        guard level > 0.002 else {
            guard thinking, !reduceMotion else { return 1 }
            return 1 + 0.45 * CGFloat(max(0, sin(t * 2 * .pi / 1.6 - Double(index) * 0.9)))
        }
        let voice = CGFloat(min(level * 10, 1))
        let wave = 0.7 + 0.3 * sin(t * 9 + Double(index) * 1.7)
        return 1 + voice * 0.9 * CGFloat(wave)
    }
}

/// The call's waveform: the last levels as bars, newest on the right, mirrored about the
/// middle. It moves with the voice, and lies flat (dots) when nothing is heard.
struct Waveform: View {
    let levels: [Float]
    var color: Color = Presence.green
    var height: CGFloat = 64

    var body: some View {
        HStack(alignment: .center, spacing: 3) {
            ForEach(Array(levels.enumerated()), id: \.offset) { index, level in
                Capsule()
                    .fill(color.opacity(0.35 + 0.65 * Double(index + 1) / Double(max(levels.count, 1))))
                    .frame(width: 4, height: Waveform.bar(level, height: height))
            }
        }
        .frame(height: height)
        .animation(.easeOut(duration: 0.08), value: levels)
        .accessibilityHidden(true)
    }

    /// A level as a bar's height: speech (0.02 to 0.2) fills it, the room barely shows. The
    /// square root, so a quiet voice still moves it.
    static func bar(_ level: Float, height: CGFloat) -> CGFloat {
        let shown = min(1, (max(0, level) / 0.15).squareRoot())
        return max(4, height * CGFloat(shown))
    }
}

/// A quiet pill button ("New", "Stop", "Try again").
struct PillButtonStyle: ButtonStyle {
    var filled = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 15, weight: .medium))
            .foregroundStyle(filled ? Color.white : Presence.ink)
            .padding(.horizontal, 18)
            .padding(.vertical, 10)
            .background(Capsule().fill(filled ? Presence.greenDeep : Presence.card))
            .overlay(Capsule().strokeBorder(filled ? Color.clear : Presence.line, lineWidth: 1))
            .opacity(configuration.isPressed ? 0.75 : 1)
            .contentShape(Capsule())
    }
}

/// A receipt under an answer: a tool Ira used.
struct ReceiptChip: View {
    let text: String

    var body: some View {
        HStack(spacing: 5) {
            Circle().fill(Presence.green).frame(width: 4, height: 4)
            Text(text).font(Presence.mono).foregroundStyle(Presence.muted)
        }
        .padding(.horizontal, 7)
        .padding(.vertical, 3)
        .overlay(RoundedRectangle(cornerRadius: 5).strokeBorder(Presence.line, lineWidth: 1))
    }
}

/// A label with a dot, uppercase and tracked: "● DROP", "● LIVE CALL".
struct DotLabel: View {
    let text: String
    var color: Color = Presence.green

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 6, height: 6)
            Text(text.uppercased())
                .font(Presence.label)
                .tracking(1.1)
                .foregroundStyle(color == Presence.green ? Presence.muted : color)
        }
    }
}

/// A quiet card: the Now cards on an empty conversation.
struct NowCard: View {
    let label: String
    let value: String
    let detail: String
    var color: Color = Presence.green

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            DotLabel(text: label, color: color)
            Text(value).font(Presence.secondary.weight(.medium)).foregroundStyle(Presence.ink).lineLimit(1)
            Text(detail).font(.system(size: 12)).foregroundStyle(Presence.muted).lineLimit(2)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(Presence.card))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Presence.line, lineWidth: 1))
    }
}

/// "Good evening." in the serif, the part of the day in green italics.
struct Greeting: View {
    var date = Date()

    var body: some View {
        let hour = Calendar.current.component(.hour, from: date)
        let part = hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening"
        (Text("Good ").foregroundColor(Presence.ink)
            + Text(part).italic().foregroundColor(Presence.green)
            + Text(".").foregroundColor(Presence.ink))
            .font(Presence.serif(32))
            .multilineTextAlignment(.center)
    }
}
