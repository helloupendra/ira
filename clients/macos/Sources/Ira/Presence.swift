import AppKit
import SwiftUI

/// Ira's look, "Presence": calm and dark first, with one hero object, the lens. Colours come
/// from these tokens only, each with its light-mode value.
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

    /// The serif, for the greeting and the words heard while listening only (New York).
    static func serif(_ size: CGFloat) -> Font { .system(size: size, weight: .regular, design: .serif) }
    static let body = Font.system(size: 15)
    static let secondary = Font.system(size: 13)
    static let label = Font.system(size: 11, weight: .medium)
    static let mono = Font.system(size: 11, design: .monospaced)

    /// "dark" (the default), "light" or "system".
    static func appearance(_ look: String) -> NSAppearance? {
        switch look {
        case "light": return NSAppearance(named: .aqua)
        case "system": return nil
        default: return NSAppearance(named: .darkAqua)
        }
    }

    private static func dynamic(dark: UInt32, light: UInt32) -> Color {
        dynamic(dark: (dark, 1), light: (light, 1))
    }

    private static func dynamic(dark: (UInt32, Double), light: (UInt32, Double)) -> Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            let (hex, alpha) = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
            return NSColor(hex: hex, alpha: alpha)
        })
    }
}

extension NSColor {
    convenience init(hex: UInt32, alpha: Double = 1) {
        self.init(
            srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
    }
}

extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(nsColor: NSColor(hex: hex, alpha: opacity))
    }
}

/// The lens: a small glass sphere with Ira's four bars of light inside. Small above the
/// greeting, large while listening (its bars follow the voice), 30 pt beside each answer.
struct Lens: View {
    var size: CGFloat
    /// The voice level, 0 to about 0.1 (the microphone's RMS); the bars follow it.
    var level: Float = 0
    var breathing = false
    /// Hairline rings around it: one at rest, two while listening, none as an avatar.
    var rings = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorScheme) private var scheme

    private static let bars: [CGFloat] = [0.17, 0.33, 0.42, 0.25]

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !breathing && level <= 0)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            // Scale 1 to 1.02 and back over 4 seconds; still when the person prefers less motion.
            let breathe = breathing && !reduceMotion ? 1 + 0.01 * (1 - cos(t * .pi / 2)) : 1
            ZStack {
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
        }
        .frame(width: size + CGFloat(rings) * size * 0.22, height: size + CGFloat(rings) * size * 0.22)
        .accessibilityHidden(true)
    }

    private var sphere: some View {
        Circle()
            .fill(RadialGradient(
                colors: [Color(hex: 0x1C5F4F), Color(hex: 0x0F3A30), Color(hex: 0x08201B)],
                center: UnitPoint(x: 0.5, y: 0.38), startRadius: 0, endRadius: size * 0.62))
            .overlay(Circle().fill(RadialGradient(
                colors: [Color.white.opacity(0.22), .clear],
                center: UnitPoint(x: 0.35, y: 0.28), startRadius: 0, endRadius: size * 0.42)))
            // An inner light at the top and a shade at the bottom.
            .overlay(Circle().strokeBorder(
                LinearGradient(colors: [Color.white.opacity(0.18), .clear], startPoint: .top, endPoint: .center),
                lineWidth: max(1, size / 96)))
            .overlay(Circle().fill(LinearGradient(colors: [.clear, Color.black.opacity(0.28)], startPoint: .center, endPoint: .bottom)))
            .frame(width: size, height: size)
            .shadow(
                color: Color(hex: 0x1F6F5C, opacity: scheme == .dark ? 0.55 : 0.3),
                radius: size * 0.23, y: size * 0.16)
    }

    /// How tall a bar stands now: as drawn at rest, taller with the voice.
    private func lift(_ index: Int, _ t: TimeInterval) -> CGFloat {
        guard level > 0.002 else { return 1 }
        let voice = CGFloat(min(level * 10, 1))
        let wave = 0.7 + 0.3 * sin(t * 9 + Double(index) * 1.7)
        return 1 + voice * 0.9 * CGFloat(wave)
    }
}

/// A quiet pill button ("New", "Drop · 1 new", "Cancel").
struct PillButtonStyle: ButtonStyle {
    var filled = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(filled ? Color.white : Presence.ink)
            .padding(.horizontal, 14)
            .padding(.vertical, 6)
            .background(Capsule().fill(filled ? Presence.greenDeep : Presence.card))
            .overlay(Capsule().strokeBorder(filled ? Color.clear : Presence.line, lineWidth: 1))
            .opacity(configuration.isPressed ? 0.75 : 1)
            .contentShape(Capsule())
    }
}

/// A key hint inside the ask pill, such as "⌥Space".
struct KeyHint: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(Presence.muted)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .overlay(RoundedRectangle(cornerRadius: 5).strokeBorder(Presence.line, lineWidth: 1))
    }
}

/// A receipt under an answer: a tool Ira used and how long it took.
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

/// A label with a dot, uppercase and tracked: "● DROP", "● WAITING FOR YOU".
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

/// A quiet card: the Now cards on an empty Chat.
struct NowCard: View {
    let label: String
    let value: String
    let detail: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            DotLabel(text: label)
            Text(value).font(Presence.secondary.weight(.medium)).foregroundStyle(Presence.ink).lineLimit(1)
            Text(detail).font(.system(size: 12)).foregroundStyle(Presence.muted).lineLimit(1)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Presence.card))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Presence.line, lineWidth: 1))
    }
}
