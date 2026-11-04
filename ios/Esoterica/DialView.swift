import NightPlan
import NightRadio
import SwiftUI
import UIKit

/// The radio, and nothing else: a dark band printed "DM" with OFF and the three stations, a needle,
/// and a serrated wheel along the bottom. A horizontal drag on the wheel turns it; the full wheel
/// width moves the needle half the dial. The radio always starts off.
struct DialView: View {
    let engine: RadioEngine
    let audio: AudioSessionController
    @Bindable var model: DialModel

    /// Placeholders (docs/project-state.md, "Plan 9", Task 9).
    static let travelPerWheelWidth = 0.5
    static let touchPoints: CGFloat = 3
    static let snapSeconds = 0.35

    /// The last place the radio was left on (UserDefaults `needle`), drawn as a faint tick.
    @State private var remembered: Double? = DialView.loadRemembered()
    @State private var dragStart: Double?
    @State private var lastX: CGFloat = 0
    @State private var moved: CGFloat = 0
    @State private var detent: Int?
    @State private var light = UIImpactFeedbackGenerator(style: .light)
    @State private var rigid = UIImpactFeedbackGenerator(style: .rigid)

    private var needle: Double {
        get { model.needle }
        nonmutating set { model.needle = newValue }
    }

    private static let ink = Color(red: 0.86, green: 0.70, blue: 0.48)       // warm, dim dial print
    private static let needleColor = Color(red: 0.95, green: 0.42, blue: 0.22)

    var body: some View {
        GeometryReader { geo in
            VStack(spacing: 0) {
                Spacer()
                band(width: geo.size.width - 32)
                    .padding(.horizontal, 16)
                Spacer()
                wheel(width: geo.size.width - 32)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 40)
            }
        }
        .background(Color.black.ignoresSafeArea())
    }

    // MARK: The band

    private func band(width: CGFloat) -> some View {
        let inner = width - 32                       // the needle's travel, inset from the band's ends
        func x(_ p: Double) -> CGFloat { 16 + inner * CGFloat(p) }
        return ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(white: 0.06))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Self.ink.opacity(0.18), lineWidth: 1))
            // Scale: a tick every 0.05 of travel, longer every 0.1.
            Canvas { ctx, size in
                for i in stride(from: 0, through: 100, by: 5) {
                    let p = Double(i) / 100
                    let h: CGFloat = i % 10 == 0 ? 10 : 5
                    var path = Path()
                    path.move(to: CGPoint(x: x(p), y: size.height - 18))
                    path.addLine(to: CGPoint(x: x(p), y: size.height - 18 - h))
                    ctx.stroke(path, with: .color(Self.ink.opacity(0.3)), lineWidth: 1)
                }
                if let r = remembered {
                    var tick = Path()
                    tick.move(to: CGPoint(x: x(r), y: 8))
                    tick.addLine(to: CGPoint(x: x(r), y: size.height - 8))
                    ctx.stroke(tick, with: .color(Self.needleColor.opacity(0.18)), lineWidth: 2)
                }
            }
            Text("DM")
                .font(.system(size: 13, weight: .semibold, design: .serif))
                .tracking(3)
                .foregroundStyle(Self.ink.opacity(0.55))
                .position(x: width - 30, y: 18)
            Text("OFF")
                .font(.system(size: 11, weight: .medium, design: .serif))
                .tracking(2)
                .foregroundStyle(Self.ink.opacity(0.5))
                .position(x: x(Dial.offZone / 2) + 13, y: 70)
            ForEach(StationRecipe.all, id: \.id) { s in
                Text(s.title)
                    .font(.system(size: 11, weight: .regular, design: .serif))
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
                    .frame(width: 84)
                    .foregroundStyle(Self.ink.opacity(0.6))
                    .position(x: min(max(x(s.dialPosition), 44), width - 44), y: 70)
            }
            Rectangle()
                .fill(Self.needleColor.opacity(0.85))
                .frame(width: 2, height: 112)
                .position(x: x(needle), y: 70)
        }
        .frame(width: width, height: 140)
    }

    // MARK: The wheel

    private func wheel(width: CGFloat) -> some View {
        Canvas { ctx, size in
            // Ridges every 9 pt, sliding with the needle; shaded like a drum seen edge-on.
            let spacing: CGFloat = 9
            let offset = CGFloat(needle / Self.travelPerWheelWidth) * size.width
            let phase = offset.truncatingRemainder(dividingBy: spacing)
            var xr = -phase
            while xr < size.width + spacing {
                let u = max(0, min(1, xr / size.width))
                let shade = 0.08 + 0.22 * sin(Double.pi * u)
                var ridge = Path()
                ridge.move(to: CGPoint(x: xr, y: 6))
                ridge.addLine(to: CGPoint(x: xr, y: size.height - 6))
                ctx.stroke(ridge, with: .color(Color(white: shade)), lineWidth: 3)
                xr += spacing
            }
        }
        .frame(width: width, height: 64)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(white: 0.03)))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .contentShape(Rectangle())
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { drag in turn(drag, wheelWidth: width) }
                .onEnded { _ in release() }
        )
    }

    private func turn(_ drag: DragGesture.Value, wheelWidth: CGFloat) {
        if dragStart == nil {
            dragStart = needle
            lastX = drag.location.x
            moved = 0
            detent = Dial.detentIndex(needle)
            light.prepare()
            rigid.prepare()
            // The dial is the only control: turning it after a lost route or an interruption plays.
            if audio.isPaused { audio.resume() }
        }
        moved += abs(drag.location.x - lastX)
        lastX = drag.location.x
        let raw = (dragStart ?? needle) + Double(drag.translation.width / wheelWidth) * Self.travelPerWheelWidth
        let next = min(max(raw, 0), 1)
        let wasOn = needle >= Dial.offZone
        let nowOn = next >= Dial.offZone
        if nowOn && !wasOn { audio.activate() }  // before setNeedle starts the engine
        needle = next
        engine.setNeedle(next)
        audio.needleMoved(to: next)
        if moved > Self.touchPoints {
            engine.wheelTouched()
            moved = 0
        }
        let d = Dial.detentIndex(next)
        if nowOn != wasOn {
            rigid.impactOccurred()
        } else if let last = detent, d != last {
            light.impactOccurred()
        }
        detent = d
    }

    /// The needle settles on a nearby station. The engine hears the settled position at once; only
    /// the drawing animates, and the animation is not a turn of the wheel.
    private func release() {
        dragStart = nil
        let settled = Dial.snapped(needle, stations: StationRecipe.all)
        if settled != needle {
            engine.setNeedle(settled)
            audio.needleMoved(to: settled)
            withAnimation(.easeOut(duration: Self.snapSeconds)) { needle = settled }
        }
        detent = Dial.detentIndex(settled)
        if settled >= Dial.offZone {
            UserDefaults.standard.set(settled, forKey: "needle")
            remembered = settled
        }
    }

    private static func loadRemembered() -> Double? {
        guard let v = UserDefaults.standard.object(forKey: "needle") as? Double, v >= Dial.offZone else { return nil }
        return v
    }
}
