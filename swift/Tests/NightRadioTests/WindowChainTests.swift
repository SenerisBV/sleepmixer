import Testing
import Foundation
import NightDSP
import NightPlan
@testable import NightRadio

private let sr = 44100.0
private let block = 2048

private func renderWindow(_ w: inout WindowChain, seconds: Double) -> (l: [Float], r: [Float]) {
    let total = Int(seconds * sr)
    var l = [Float](), r = [Float]()
    l.reserveCapacity(total); r.reserveCapacity(total)
    var bl = [Float](repeating: 0, count: block), br = bl
    var done = 0
    while done < total {
        let n = min(block, total - done)
        w.render(left: &bl, right: &br, count: n)
        l.append(contentsOf: bl[0..<n]); r.append(contentsOf: br[0..<n])
        done += n
    }
    return (l, r)
}

private func rms(_ x: [Float]) -> Double {
    (x.reduce(0.0) { $0 + Double($1) * Double($1) } / Double(max(x.count, 1))).squareRoot()
}

private func monoSum(_ w: (l: [Float], r: [Float])) -> [Float] {
    zip(w.l, w.r).map { ($0 + $1) / 2 }
}

private func stationRMS(seed: UInt64, seconds: Double) -> Double {
    let c = DriftClock(seed: seed)
    c.touch(at: 0)
    var chain = StationChain(recipe: StationRecipe.all[0], bundle: nil, seed: seed, clock: c, sampleRate: sr)
    var out = [Float](), buf = [Float](repeating: 0, count: block)
    var done = 0
    let total = Int(seconds * sr)
    while done < total {
        let n = min(block, total - done)
        chain.render(into: &buf, count: n)
        out.append(contentsOf: buf[0..<n]); done += n
    }
    return rms(out)
}

@Test func eachNightHasItsSounds() {
    #expect(WindowChain(seed: 1, sampleRate: sr, night: .rain).activeSounds == ["rain"])
    #expect(WindowChain(seed: 1, sampleRate: sr, night: .rainThunder).activeSounds == ["rain", "thunder"])
    #expect(WindowChain(seed: 1, sampleRate: sr, night: .cricketsStream).activeSounds == ["crickets", "stream"])
    #expect(WindowChain(seed: 1, sampleRate: sr, night: .fire).activeSounds == ["fire"])
    // nil night follows Weather.night.
    for seed in UInt64(1)...20 {
        #expect(WindowChain(seed: seed, sampleRate: sr).night == Weather.night(seed: seed))
    }
}

// A roll starts within the first 120 s of its 240 s cell and is born with certainty at full rate,
// so the first 5 minutes always hold one (30 minutes would only make the debug build slower).
@Test func rainThunderSoundsThunderEarly() {
    var rt = WindowChain(seed: 4, sampleRate: sr, night: .rainThunder)
    var rain = WindowChain(seed: 4, sampleRate: sr, night: .rain)
    let a = renderWindow(&rt, seconds: 300), b = renderWindow(&rain, seconds: 300)
    #expect(a.l != b.l, "thunder is present on a rainThunder night")
}

@Test func windowSitsUnderAStation() {
    for seed in [UInt64(7), 12] {
    let station = stationRMS(seed: seed, seconds: 60)
    for night in WindowNight.allCases {
        var w = WindowChain(seed: seed, sampleRate: sr, night: night)
        let level = rms(monoSum(renderWindow(&w, seconds: 60)))
        let under = 20 * log10(station / level)
        print("windowSitsUnderAStation: seed \(seed) \(night) is \(under) dB under a station")
        #expect(under > 6 && under < 10, "\(night): \(under) dB")
    }
    }
}

@Test func windowIsStereo() {
    var w = WindowChain(seed: 3, sampleRate: sr, night: .rain)
    let o = renderWindow(&w, seconds: 30)
    #expect(o.l != o.r)
    var sxy = 0.0, sxx = 0.0, syy = 0.0
    for i in o.l.indices {
        let x = Double(o.l[i]), y = Double(o.r[i])
        sxy += x * y; sxx += x * x; syy += y * y
    }
    let corr = sxy / (sxx * syy).squareRoot()
    print("windowIsStereo: correlation \(corr)")
    #expect(corr > 0.2 && corr < 0.95, "\(corr)")
}

@Test func widthMixKeepsPowerAndSetsCorrelation() {
    for w in [0.0, 0.3, 0.6, 1.0] {
        let m = WindowChain.mix(width: w)
        #expect(abs(Double(m.a * m.a + m.b * m.b) - 1) < 1e-6)
        #expect(abs(Double(2 * m.a * m.b) - (1 - w)) < 1e-6)
    }
}

@Test func suddenSilentDeepInNight() {
    let start = 5.0 * 3600
    #if DEBUG
    let minutes = 5.0      // the debug build is about 50x slower; the release run does the full 30
    #else
    let minutes = 30.0
    #endif
    var rt = WindowChain(seed: 4, sampleRate: sr, startSecond: start, night: .rainThunder)
    var rain = WindowChain(seed: 4, sampleRate: sr, startSecond: start, night: .rain)
    let a = renderWindow(&rt, seconds: minutes * 60), b = renderWindow(&rain, seconds: minutes * 60)
    #expect(a.l == b.l, "thunder contributes nothing 5 h in (L)")
    #expect(a.r == b.r, "thunder contributes nothing 5 h in (R)")
    // (rainThunderSoundsThunderEarly shows the same comparison has teeth at switch-on.)
}

@Test func windowTakesNoClock() throws {
    var w = WindowChain(seed: 1, sampleRate: sr)   // builds with no DriftClock
    var l = [Float](repeating: 0, count: 64), r = l
    w.render(left: &l, right: &r, count: 64)
    let file = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Sources/NightRadio/WindowChain.swift")
    let text = try String(contentsOf: file, encoding: .utf8)
    #expect(!text.contains("DriftClock"))
    #expect(!text.contains("DriftClock".lowercased() + "("))
}

@Test func windowIsDeterministic() {
    for night in WindowNight.allCases {
        var a = WindowChain(seed: 9, sampleRate: sr, night: night)
        var b = WindowChain(seed: 9, sampleRate: sr, night: night)
        let x = renderWindow(&a, seconds: 10), y = renderWindow(&b, seconds: 10)
        #expect(x.l == y.l)
        #expect(x.r == y.r)
        #expect(x.l.allSatisfy { abs($0) <= 1 })
    }
}

@Test func windowRendersFastEnough() {
    let seed: UInt64 = 11
    func time(_ f: () -> Void) -> Double {
        let t0 = ContinuousClock.now
        f()
        let e = ContinuousClock.now - t0
        return Double(e.components.seconds) + Double(e.components.attoseconds) * 1e-18
    }
    let c = DriftClock(seed: seed); c.touch(at: 0)
    var chains = StationRecipe.all.map { StationChain(recipe: $0, bundle: nil, seed: seed, clock: c, sampleRate: sr) }
    var buf = [Float](repeating: 0, count: block)
    let total = Int(60 * sr)
    let stations = time {
        var done = 0
        while done < total {
            let n = min(block, total - done)
            for i in chains.indices { chains[i].render(into: &buf, count: n) }
            done += n
        }
    }
    var worst = 0.0
    for night in WindowNight.allCases {
        var w = WindowChain(seed: seed, sampleRate: sr, night: night)
        var bl = buf, br = buf
        let t = time {
            var done = 0
            while done < total {
                let n = min(block, total - done)
                w.render(left: &bl, right: &br, count: n)
                done += n
            }
        }
        print("windowRendersFastEnough: \(night) \(t) s, ratio to 3 stations \(t / stations)")
        worst = max(worst, t)
    }
    print("windowRendersFastEnough: 3 stations \(stations) s, worst window \(worst) s, ratio \(worst / stations)")
    #expect(worst <= stations, "window \(worst) s vs stations \(stations) s")
}
