import Foundation
import NightPlan

/// Rich round chimes: soft mallet strikes on a pentatonic set, each ringing a body of
/// inharmonic partials, a slow bloom and a pair of beating partials.
///
/// Seekable by construction. Strikes live on a fixed grid of cells; each strike reads the warp
/// once, at its birth, and every sample it makes is a pure function of the absolute frame:
/// oscillator phases come from `frame - birthFrame`, the mallet filter runs from the strike's
/// own birth, and any recurrence used for speed restarts on a block grid aligned to absolute
/// frames. Contributions are summed in a fixed order (cell index, then element), so a render
/// started at any second is bit-identical to the same frames of a continuous render.
public struct ChimesScene: Scene {
    public static let kind = SceneKind.chimes
    public let elements = ["strike", "body", "bloom", "beating"]

    // MARK: - Values from the brief (placeholders recorded in Task 8)

    static let cellSeconds = 2.2
    static let offsetSeconds = 1.6
    static let density = 0.6
    static let rootRange = 196.0...392.0
    static let pentatonic: [Double] = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21]
    static let slowDropSemitones = 3.0
    public static let strikeAttack = 0.02
    public static let strikeDecay = 0.08
    static let bodyRatios = [1.0, 2.0, 2.76, 4.07]
    static let bodyDecays = [6.0, 3.0, 2.0, 1.2]
    static let bodyAmps = [1.0, 0.5, 0.35, 0.2]
    static let bloomAttack = 1.5
    static let bloomDecay = 12.0
    static let beatOffsetHz = 0.35
    static let beatDecay = 8.0
    static let lookbackSeconds = 60.0

    // MARK: - Invented values (placeholders recorded in Task 8)

    static let rootStream: UInt64 = 0
    static let noiseStream: UInt64 = 5
    static let malletRatio = 2.0          // mallet band centre, × the strike's fundamental
    static let malletMaxHz = 2500.0
    static let malletQ = 1.2
    static let strikeLevel = 0.3
    static let malletSeconds = strikeAttack + 12 * strikeDecay
    static let bodyAttack = 0.02
    static let bloomAmps = [0.35, 0.25]   // fundamental, octave below
    static let beatAttack = 0.3
    static let beatAmps = [0.2, 0.2]      // below, above
    static let tailTimeConstants = 7.0    // an element ends 7 decay constants (-61 dB) after its attack...
    static let lifetimeCap = 58.0         // ...or at 58 s, inside the 60 s lookback
    static let fadeSeconds = 4.0          // every element fades to true zero before it ends
    static let fadeFraction = 0.25        // (or over its last quarter, if shorter)
    static let blockFrames = 256          // recurrences restart on this absolute-frame grid
    static let masterGain = 0.1          // a dense plain passage peaks near -6 dBFS (median over seeds)

    // MARK: - The grid (pure, shared by the renderer and the tests)

    private static func birthSecond(seed: UInt64, cell: Int) -> Double {
        Double(cell) * cellSeconds + NightRandom.unit(seed, 2, UInt64(cell)) * offsetSeconds
    }

    /// Birth second and the warp it freezes, or nil when the cell is empty.
    private static func strike(seed: UInt64, cell: Int, warp: Curve<WarpDepth>) -> (birth: Double, warp: WarpDepth)? {
        guard cell >= 0 else { return nil }
        let birth = birthSecond(seed: seed, cell: cell)
        let w = warp(birth)
        guard NightRandom.unit(seed, 1, UInt64(cell)) < density / (1 + 2 * w.slowness) else { return nil }
        return (birth, w)
    }

    private static func frame(_ second: Double, _ sr: Double) -> Int { Int((second * sr).rounded()) }

    /// Birth times (frame-quantised seconds) of strikes born in `[from, to)`.
    static func strikeTimes(seed: UInt64, sampleRate: Double, warp: Curve<WarpDepth>, from: Double, to: Double) -> [Double] {
        let first = max(0, Int(((from - offsetSeconds) / cellSeconds).rounded(.down)))
        let last = Int((to / cellSeconds).rounded(.up))
        guard first <= last else { return [] }
        return (first...last).compactMap { cell in
            guard let s = strike(seed: seed, cell: cell, warp: warp) else { return nil }
            let t = Double(frame(s.birth, sampleRate)) / sampleRate
            return t >= from && t < to ? t : nil
        }
    }

    /// Per-element gains in dB, in `elements` order, for the strike in cell `index`.
    static func elementGains(seed: UInt64, index: UInt64, warp: Curve<WarpDepth>) -> [Double] {
        gains(seed: seed, cell: Int(index), proportion: warp(birthSecond(seed: seed, cell: Int(index))).proportion)
    }

    private static func gains(seed: UInt64, cell: Int, proportion: Double) -> [Double] {
        Proportion.gainsDB(seed: seed, stream: 4, index: UInt64(cell), count: 4, proportion: proportion)
    }

    /// The strike's fundamental for the warp it froze at birth: the seed's root, the cell's
    /// pentatonic degree, lowered by `slowDropSemitones × slowness`. The renderer uses this too.
    static func fundamental(seed: UInt64, cell: Int, warp: WarpDepth) -> Double {
        let r = rootRange
        let root = r.lowerBound * pow(r.upperBound / r.lowerBound, NightRandom.unit(seed, rootStream, 0))
        let degree = pentatonic[min(Int(NightRandom.unit(seed, 3, UInt64(cell)) * 10), 9)]
        return root * pow(2, (degree - slowDropSemitones * warp.slowness) / 12)
    }

    public static func strikeEnvelope(t: Double) -> Double {
        Envelope.attackDecay(t: t, attack: strikeAttack, decay: strikeDecay)
    }

    // MARK: - Voices

    private struct Partial {
        var amp: Double
        var omega: Double            // radians per frame
        var cosW: Double, sinW: Double
        var attack: Double, decay: Double, step: Double
        var lifeFrames: Int, fadeFrames: Int
    }

    private struct Voice {
        var cell: Int
        var birth: Int               // absolute frame
        var end: Int                 // first absolute frame with no sound
        var mallet: [Double]         // finished strike element, from birth
        var partials: [Partial]
    }

    private let seed: UInt64
    private let sr: Double
    private let warp: Curve<WarpDepth>
    private var position: Int
    private var nextCell: Int
    private var voices: [Voice] = []
    private var block: [Double]
    private var blockStart = Int.min

    public init(seed: UInt64, sampleRate: Double, warp: Curve<WarpDepth>, startSecond: Double) {
        self.seed = seed
        self.sr = sampleRate
        self.warp = warp
        let start = startSecond.isFinite ? max(0, startSecond) : 0
        position = Self.frame(start, sampleRate)
        // Every strike born up to the lookback before the start may still be sounding.
        nextCell = max(0, Int(((start - Self.lookbackSeconds) / Self.cellSeconds).rounded(.down)))
        block = [Double](repeating: 0, count: Self.blockFrames)
    }

    private func makeVoice(cell: Int) -> Voice? {
        guard let s = Self.strike(seed: seed, cell: cell, warp: warp) else { return nil }
        let slow = s.warp.slowness
        let birth = Self.frame(s.birth, sr)
        let f0 = Self.fundamental(seed: seed, cell: cell, warp: s.warp)
        let g = Self.gains(seed: seed, cell: cell, proportion: s.warp.proportion).map { pow(10, $0 / 20) * Self.masterGain }

        var partials: [Partial] = []
        func add(_ hz: Double, _ amp: Double, _ attack: Double, _ decay: Double) {
            guard hz > 0, hz < 0.45 * sr else { return }
            let lifeSeconds = min(attack + Self.tailTimeConstants * decay, Self.lifetimeCap)
            let omega = 2 * Double.pi * hz / sr
            partials.append(Partial(
                amp: amp, omega: omega, cosW: cos(omega), sinW: sin(omega),
                attack: attack, decay: decay, step: exp(-1 / (sr * decay)),
                lifeFrames: Self.frame(lifeSeconds, sr),
                fadeFrames: max(1, Self.frame(min(Self.fadeSeconds, Self.fadeFraction * lifeSeconds), sr))))
        }
        for k in 0..<4 {
            add(f0 * Self.bodyRatios[k], Self.bodyAmps[k] * g[1], Self.bodyAttack, Self.bodyDecays[k] * (1 + 2 * slow))
        }
        add(f0, Self.bloomAmps[0] * g[2], Self.bloomAttack, Self.bloomDecay * (1 + slow))
        add(f0 / 2, Self.bloomAmps[1] * g[2], Self.bloomAttack, Self.bloomDecay * (1 + slow))
        add(f0 - Self.beatOffsetHz, Self.beatAmps[0] * g[3], Self.beatAttack, Self.beatDecay)
        add(f0 + Self.beatOffsetHz, Self.beatAmps[1] * g[3], Self.beatAttack, Self.beatDecay)

        // The mallet: hashed noise through a filter zeroed at birth, then the strike envelope.
        var filter = Biquad.bandpass(center: min(f0 * Self.malletRatio, Self.malletMaxHz), q: Self.malletQ, sampleRate: sr)
        let noiseSeed = NightRandom.hash(seed, Self.noiseStream, UInt64(cell))
        let level = Self.strikeLevel * g[0]
        let mallet = (0..<Self.frame(Self.malletSeconds, sr)).map { k in
            let x = filter.process(Float(NightRandom.signed(noiseSeed, Self.noiseStream, UInt64(k))))
            return Double(x) * Self.strikeEnvelope(t: Double(k) / sr) * level
        }

        let end = birth + max(mallet.count, partials.map(\.lifeFrames).max() ?? 0)
        return Voice(cell: cell, birth: birth, end: end, mallet: mallet, partials: partials)
    }

    /// Renders the absolute block starting at `b` (a multiple of `blockFrames`) into `block`.
    private mutating func renderBlock(_ b: Int) {
        let n = Self.blockFrames
        let blockEnd = b + n
        voices.removeAll { $0.end <= b }
        while Double(nextCell) * Self.cellSeconds * sr <= Double(blockEnd) {
            if let v = makeVoice(cell: nextCell) { voices.append(v) }
            nextCell += 1
        }
        for i in 0..<n { block[i] = 0 }
        for v in voices where v.birth < blockEnd {
            // strike
            let mFirst = max(b, v.birth), mLast = min(blockEnd, v.birth + v.mallet.count)
            if mFirst < mLast {
                for f in mFirst..<mLast { block[f - b] += v.mallet[f - v.birth] }
            }
            // body, bloom, beating
            for p in v.partials {
                let first = max(b, v.birth), last = min(blockEnd, v.birth + p.lifeFrames)
                guard first < last else { continue }
                var k = first - v.birth
                let phase = p.omega * Double(k)
                var c = cos(phase), s = sin(phase)
                var e = 0.0, decaying = false
                let fadeStart = p.lifeFrames - p.fadeFrames
                for f in first..<last {
                    let t = Double(k) / sr
                    var env: Double
                    if t < p.attack {
                        env = Envelope.attackDecay(t: t, attack: p.attack, decay: p.decay)
                    } else if decaying {
                        e *= p.step
                        env = e
                    } else {
                        e = Envelope.attackDecay(t: t, attack: p.attack, decay: p.decay)
                        decaying = true
                        env = e
                    }
                    if k >= fadeStart {
                        env *= 0.5 + 0.5 * cos(Double.pi * Double(k - fadeStart) / Double(p.fadeFrames))
                    }
                    block[f - b] += p.amp * env * s
                    let c2 = c * p.cosW - s * p.sinW
                    s = s * p.cosW + c * p.sinW
                    c = c2
                    k += 1
                }
            }
        }
        blockStart = b
    }

    public mutating func render(into out: inout [Float], count: Int) {
        var written = 0
        while written < count {
            let b = (position / Self.blockFrames) * Self.blockFrames
            if b != blockStart { renderBlock(b) }
            let take = min(b + Self.blockFrames - position, count - written)
            for i in 0..<take { out[written + i] = Float(block[position - b + i]) }
            written += take
            position += take
        }
    }
}
