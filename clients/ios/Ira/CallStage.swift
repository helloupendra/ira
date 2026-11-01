import IraPhoneKit
import SwiftUI

/// A call, over the whole screen: the large lens with its bars on the voice, one word for
/// what is happening now (Listening, Hearing you, Thinking, Speaking), a waveform that moves
/// with the voice, what Ira hears and says, and End. Built from plain values, so it is drawn
/// the same in the app and in a snapshot.
struct CallStage<Accessory: View>: View {
    let phase: CallPhase
    let level: Float
    let levels: [Float]
    let caption: String
    /// Ira's latest answer in this call, as it is written.
    let answer: String
    let live: Bool
    var onEnd: () -> Void = {}
    var onStop: () -> Void = {}
    var onRetry: () -> Void = {}
    var onKeyboard: () -> Void = {}
    @ViewBuilder var accessory: () -> Accessory
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ZStack {
            Presence.bg.ignoresSafeArea()
            RadialGradient(
                colors: [tint.opacity(scheme == .dark ? 0.22 : 0.12), .clear],
                center: UnitPoint(x: 0.5, y: 0.34), startRadius: 0, endRadius: 360)
                .ignoresSafeArea()
                .animation(.easeOut(duration: 0.3), value: phase)
            VStack(spacing: 0) {
                HStack {
                    DotLabel(text: live ? "Live call" : "Phone mode", color: phase == .micSilent ? Presence.warn : Presence.green)
                    Spacer()
                }
                .padding(.horizontal, 24)
                .padding(.top, 12)
                Spacer(minLength: 12)
                Lens(
                    size: 176, level: phase == .micSilent ? 0 : level, breathing: phase == .speaking,
                    heartbeat: phase == .listening || phase == .hearing, thinking: phase == .thinking,
                    rings: 2, tint: tint)
                    // Dimmed when the microphone gives nothing: nothing is coming through.
                    .saturation(phase == .micSilent ? 0.15 : 1)
                    .opacity(phase == .micSilent ? 0.6 : 1)
                    .animation(.easeOut(duration: 0.3), value: phase)
                    .padding(.bottom, 28)
                Text(phase.title)
                    .font(Presence.serif(36))
                    .foregroundStyle(phase == .micSilent ? Presence.warn : Presence.ink)
                    .accessibilityIdentifier("call-phase")
                    .contentTransition(.opacity)
                    .animation(.easeOut(duration: 0.2), value: phase)
                Text(phase.detail)
                    .font(Presence.secondary)
                    .foregroundStyle(Presence.muted)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 36)
                    .padding(.top, 6)
                Waveform(levels: levels, color: phase == .micSilent ? Presence.warn : tint, height: 56)
                    .padding(.top, 26)
                    .opacity(phase == .connecting ? 0.25 : 1)
                words
                    .padding(.top, 18)
                    .padding(.horizontal, 28)
                accessory()
                    .padding(.horizontal, 20)
                    .padding(.top, 8)
                Spacer(minLength: 12)
                controls
                    .padding(.bottom, 20)
            }
        }
    }

    /// Green while all is well, the warning colour when the microphone gives nothing.
    private var tint: Color { phase == .micSilent ? Presence.warn : Presence.green }

    /// What Ira hears as the person speaks, else the start of her answer.
    @ViewBuilder private var words: some View {
        if !caption.isEmpty {
            Text("“\(caption)”")
                .font(Presence.serif(19).italic())
                .foregroundStyle(Presence.ink.opacity(0.85))
                .multilineTextAlignment(.center)
                .lineLimit(3)
        } else if !answer.isEmpty, phase == .speaking || phase == .thinking || phase == .listening {
            Text(answer)
                .font(Presence.body)
                .foregroundStyle(Presence.muted)
                .multilineTextAlignment(.center)
                .lineLimit(4)
        } else {
            Text(" ").font(Presence.body).lineLimit(1)
        }
    }

    private var controls: some View {
        HStack(alignment: .bottom, spacing: 28) {
            round("keyboard", label: "Type", size: 56, fill: Presence.card, foreground: Presence.ink, action: onKeyboard)
                .accessibilityIdentifier("call-keyboard")
            VStack(spacing: 8) {
                Button(action: onEnd) {
                    Image(systemName: "phone.down.fill")
                        .font(.system(size: 28, weight: .semibold))
                        .foregroundStyle(.white)
                        .frame(width: 76, height: 76)
                        .background(Circle().fill(Presence.down))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("End call")
                .accessibilityIdentifier("call-end")
                Text("End").font(.system(size: 12)).foregroundStyle(Presence.muted)
            }
            if phase == .speaking || phase == .thinking {
                round("stop.fill", label: "Stop", size: 56, fill: Presence.card, foreground: Presence.ink, action: onStop)
                    .accessibilityIdentifier("stop")
            } else if phase == .micSilent {
                round("arrow.clockwise", label: "Try again", size: 56, fill: Presence.warn.opacity(0.18), foreground: Presence.warn, action: onRetry)
                    .accessibilityIdentifier("call-retry")
            } else {
                Color.clear.frame(width: 56, height: 56 + 20)
            }
        }
    }

    private func round(_ symbol: String, label: String, size: CGFloat, fill: Color, foreground: Color, action: @escaping () -> Void) -> some View {
        VStack(spacing: 8) {
            Button(action: action) {
                Image(systemName: symbol)
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(foreground)
                    .frame(width: size, height: size)
                    .background(Circle().fill(fill))
                    .overlay(Circle().strokeBorder(Presence.line, lineWidth: 1))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(label)
            Text(label).font(.system(size: 12)).foregroundStyle(Presence.muted)
        }
    }
}

extension CallStage where Accessory == EmptyView {
    init(phase: CallPhase, level: Float, levels: [Float], caption: String, answer: String, live: Bool) {
        self.init(phase: phase, level: level, levels: levels, caption: caption, answer: answer, live: live) { EmptyView() }
    }
}
