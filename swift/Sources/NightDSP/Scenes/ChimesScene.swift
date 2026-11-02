import Foundation
import NightPlan

/// Soft-mallet chimes: felted bars on a pentatonic set. Each note is a near-pure fundamental with a
/// faint overtone two octaves up (×4) and a fainter one at ×10, each overtone dying faster than the
/// fundamental as on a real bar; no mallet noise; a raised-cosine soft start. Three tone dials,
/// frozen per note at its birth: ring (the decay time), softness (the attack) and vibrato (a slow
/// amplitude pulse). Ring and vibrato are level-neutral; proportion is power-preserving.
///
/// Seekable by construction. Notes live on a fixed grid of cells; each note reads the warp once,
/// at its birth, and every sample it makes is a pure function of the absolute frame: phases and
/// decays come from `frame - birthFrame`, and every recurrence used for speed (the partials'
/// rotations, their decay steps and the vibrato's rotation) restarts on a block grid aligned to
/// absolute frames. Contributions are summed in a fixed order (cell index, then partial), so a
/// render started at any second is bit-identical to the same frames of a continuous render.
public struct ChimesScene: Scene {
    public static let kind = SceneKind.chimes
    public let elements = ["fundamental", "fourth", "tenth"]

    // MARK: - Values from the brief (placeholders recorded in docs/project-state.md)

    static let cellSeconds = 2.2
    static let offsetSeconds = 1.6
    static let density = 0.6
    static let rootRange = 196.0...392.0
    static let pentatonic: [Double] = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21]
    static let slowDropSemitones = 3.0
    static let lookbackSeconds = 60.0
    /// The bar: partial ratios and their base amplitudes (0, -24 and -36 dB).
    static let ratios: [Double] = [1, 4, 10]
    static let baseAmps: [Double] = [1, pow(10, -24.0 / 20), pow(10, -36.0 / 20)]
    /// Ring: the fundamental's decay time constant, 1.4 s (the spike's "close to the reference")
    /// to 4.2 s (a placeholder ceiling). The partial at ×k decays with `τ / sqrt(k)`.
    static let ringRange = 1.4...4.2
    /// Softness: the raised-cosine attack, 35 ms (the spike's strike) to 0.12 s (a placeholder ceiling).
    static let attackRange = 0.035...0.12
    /// Vibrato: an amplitude pulse at 4.5 Hz, depth 0.18 × the dial.
    public static let vibratoHz = 4.5
    static let vibratoMaxDepth = 0.18
    static let tailTimeConstants = 7.0    // a note ends 7 ring time constants (-61 dB) after birth...
    static let lifetimeCap = 58.0         // ...or at 58 s, inside the 60 s lookback
    static let fadeSeconds = 4.0          // every note fades to true zero before it ends
    static let fadeFraction = 0.25        // (or over its last quarter, if shorter)

    // MARK: - Invented values (placeholders recorded in docs/project-state.md)

    static let rootStream: UInt64 = 0
    static let favouredStream: UInt64 = 4
    // Stream 5 was the bells' mallet noise; it is retired, not reused.
    static let vibratoPhaseStream: UInt64 = 6
    /// The felt mallet barely excites high partials: each partial's base amplitude is multiplied
    /// by `1 / sqrt(1 + (f / malletCornerHz)^4)` (a 4th-order magnitude rolloff at its actual
    /// frequency), before proportion redistributes power among what the mallet excites.
    static let malletCornerHz = 2000.0
    static let blockFrames = 256          // recurrences restart on this absolute-frame grid
    static let masterGain = 0.32          // a plain passage peaks near -6 dBFS (median of 600 s over 20 seeds: -6.1)

    // MARK: - Dials

    /// The ring time constant τ, linear in the dial.
    public static func ringSeconds(_ ring: Double) -> Double {
        ringRange.lowerBound + (ringRange.upperBound - ringRange.lowerBound) * ring
    }

    /// The raised-cosine attack length, linear in the dial.
    public static func attackSeconds(_ softness: Double) -> Double {
        attackRange.lowerBound + (attackRange.upperBound - attackRange.lowerBound) * softness
    }

    /// The vibrato's depth: the pulse dips by up to this fraction of the note's level.
    public static func vibratoDepth(_ v: Double) -> Double { vibratoMaxDepth * v }

    /// The lowest fundamental the scene can play: the bottom of the root range, slowed by 3 semitones.
    static let lowestFundamental = rootRange.lowerBound * pow(2, -slowDropSemitones / 12)

    /// The highest fundamental the scene can play: the top of the root range at the top degree.
    static let highestFundamental = rootRange.upperBound * pow(2, pentatonic.last! / 12)

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

    /// Birth times (frame-quantised seconds) of notes born in `[from, to)`.
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

    /// The felt mallet's rolloff at frequency `hz`.
    static func malletRolloff(_ hz: Double) -> Double {
        1 / (1 + pow(hz / malletCornerHz, 4)).squareRoot()
    }

    /// What the mallet excites on a note with fundamental `f0`: `baseAmps` times the rolloff at
    /// each partial's frequency. Proportion's power is preserved over these.
    static func malletAmps(f0: Double) -> [Double] {
        zip(baseAmps, ratios).map { $0 * malletRolloff(f0 * $1) }
    }

    /// Linear per-partial gains, in `elements` order, applied on top of `malletAmps` for the note
    /// in cell `index`. These are the gains the renderer uses.
    static func elementGains(seed: UInt64, index: UInt64, warp: Curve<WarpDepth>) -> [Double] {
        let cell = Int(index)
        let w = warp(birthSecond(seed: seed, cell: cell))
        return gains(seed: seed, cell: cell, amps: malletAmps(f0: fundamental(seed: seed, cell: cell, warp: w)),
                     proportion: w.proportion)
    }

    private static func gains(seed: UInt64, cell: Int, amps: [Double], proportion: Double) -> [Double] {
        Proportion.powerPreservingGains(seed: seed, stream: favouredStream, index: UInt64(cell),
                                        baseAmps: amps, proportion: proportion)
    }

    /// The note's fundamental for the warp it froze at birth: the seed's root, the cell's
    /// pentatonic degree, lowered by `slowDropSemitones × slowness`. The renderer uses this too.
    static func fundamental(seed: UInt64, cell: Int, warp: WarpDepth) -> Double {
        let r = rootRange
        let root = r.lowerBound * pow(r.upperBound / r.lowerBound, NightRandom.unit(seed, rootStream, 0))
        let degree = pentatonic[min(Int(NightRandom.unit(seed, 3, UInt64(cell)) * 10), 9)]
        return root * pow(2, (degree - slowDropSemitones * warp.slowness) / 12)
    }

    // MARK: - Peak bound

    /// The analytic worst-case peak, maximised over ring ∈ {0, 0.5, 1} at softness 0, slowness 0
    /// and proportion 1, with vibrato at its crest. One note can reach at most
    /// `master · sqrt(1.4/τ) · max_{f0, favoured} Σ malletAmps·g / (1 - d/2)` (f0 over the scene's
    /// range on a fine log grid, endpoints included); every cell is taken as occupied,
    /// and the k-th earlier note as at least `k·2.2 - 1.6` s older (birth offsets span 0…1.6 s),
    /// decayed by `exp(-age/τ)`. Valid for constant dials only: a ring that drops fast can reach
    /// 1.30× this bound (1.13 absolute); see "Known limitations" in docs/project-state.md.
    public static func peakBound() -> Double {
        let crest = 1 / (1 - vibratoDepth(1) / 2)
        let steps = 1024
        let loudest = (0...steps).flatMap { i -> [Double] in
            let f0 = lowestFundamental * pow(highestFundamental / lowestFundamental, Double(i) / Double(steps))
            let amps = malletAmps(f0: f0)
            return (0..<amps.count).map { fav in
                zip(amps, Proportion.powerPreservingGains(favoured: fav, baseAmps: amps, proportion: 1))
                    .map { $0 * $1 }.reduce(0, +)
            }
        }.max()!
        return [0.0, 0.5, 1.0].map { ring in
            let tau = ringSeconds(ring)
            let note = masterGain * (ringRange.lowerBound / tau).squareRoot() * loudest * crest
            let r = exp(-cellSeconds / tau)
            let older = exp(offsetSeconds / tau) * r / (1 - r)
            return note * (1 + older)
        }.max()!
    }

    // MARK: - Voices

    private struct Partial {
        var amp: Double
        var omega: Double            // radians per frame
        var cosW: Double, sinW: Double
        var tauFrames: Double        // decay time constant, in frames
        var step: Double             // per-frame decay
    }

    private struct Voice {
        var birth: Int               // absolute frame
        var end: Int                 // first absolute frame with no sound
        var partials: [Partial]
        var level: Double            // master · sqrt(1.4/τ) / (1 - d/2)
        var attack: Double           // seconds
        var attackFrames: Int
        var depth: Double            // vibrato depth d
        var vibOmega: Double, vibCos: Double, vibSin: Double, vibPhase: Double
        var lifeFrames: Int, fadeFrames: Int

        /// `amps` are the final per-partial amplitudes: `malletAmps(f0)` times the proportion gains.
        init(birth: Int, f0: Double, warp: WarpDepth, amps: [Double], phase: Double, sr: Double) {
            let tau = ChimesScene.ringSeconds(warp.ring)
            self.birth = birth
            partials = []
            for k in 0..<ChimesScene.ratios.count {
                let hz = f0 * ChimesScene.ratios[k]
                guard hz > 0, hz < 0.45 * sr else { continue }
                let omega = 2 * Double.pi * hz / sr
                let tauFrames = sr * tau / ChimesScene.ratios[k].squareRoot()
                partials.append(Partial(amp: amps[k], omega: omega,
                                        cosW: cos(omega), sinW: sin(omega),
                                        tauFrames: tauFrames, step: exp(-1 / tauFrames)))
            }
            depth = ChimesScene.vibratoDepth(warp.vibrato)
            level = ChimesScene.masterGain * (ChimesScene.ringRange.lowerBound / tau).squareRoot() / (1 - depth / 2)
            attack = ChimesScene.attackSeconds(warp.softness)
            attackFrames = Int((attack * sr).rounded(.up))
            vibOmega = 2 * Double.pi * ChimesScene.vibratoHz / sr
            vibCos = cos(vibOmega)
            vibSin = sin(vibOmega)
            vibPhase = phase
            let lifeSeconds = min(ChimesScene.tailTimeConstants * tau, ChimesScene.lifetimeCap)
            lifeFrames = ChimesScene.frame(lifeSeconds, sr)
            fadeFrames = max(1, ChimesScene.frame(min(ChimesScene.fadeSeconds, ChimesScene.fadeFraction * lifeSeconds), sr))
            end = birth + lifeFrames
        }

        /// Adds this note's frames in `[b, b + block.count)` into `block`. Every recurrence starts
        /// from closed-form values at the block's first frame, so the result depends only on `b`.
        func render(into block: inout [Double], from b: Int, sr: Double) {
            let blockEnd = b + block.count
            let first = max(b, birth), last = min(blockEnd, end)
            guard first < last else { return }
            let k0 = first - birth
            let count = last - first
            var c = [Double](repeating: 0, count: partials.count)
            var s = c, e = c
            for (i, p) in partials.enumerated() {
                let phase = p.omega * Double(k0)
                c[i] = cos(phase); s[i] = sin(phase)
                e[i] = exp(-Double(k0) / p.tauFrames)
            }
            let theta = vibOmega * Double(k0) + vibPhase
            var vc = cos(theta), vs = sin(theta)
            let fadeStart = lifeFrames - fadeFrames
            for j in 0..<count {
                let k = k0 + j
                var x = 0.0
                for i in 0..<partials.count {
                    x += partials[i].amp * e[i] * s[i]
                    let c2 = c[i] * partials[i].cosW - s[i] * partials[i].sinW
                    s[i] = s[i] * partials[i].cosW + c[i] * partials[i].sinW
                    c[i] = c2
                    e[i] *= partials[i].step
                }
                var env = level
                if k < attackFrames { env *= Envelope.raisedCosine(Double(k) / sr / attack) }
                if k >= fadeStart {
                    env *= 0.5 + 0.5 * cos(Double.pi * Double(k - fadeStart) / Double(fadeFrames))
                }
                if depth > 0 {
                    env *= 1 - depth * (0.5 - 0.5 * vc)
                    let vc2 = vc * vibCos - vs * vibSin
                    vs = vs * vibCos + vc * vibSin
                    vc = vc2
                }
                block[first - b + j] += x * env
            }
        }
    }

    /// One isolated note born at frame 0, through the same voice code as the scene: vibrato phase
    /// 0, and at `warp.proportion` the element `favoured` is the one that swells.
    static func renderNote(f: Double, warp: WarpDepth, seconds: Double, sampleRate: Double, favoured: Int = 0) -> [Float] {
        let m = malletAmps(f0: f)
        let g = Proportion.powerPreservingGains(favoured: favoured, baseAmps: m, proportion: warp.proportion)
        let voice = Voice(birth: 0, f0: f, warp: warp, amps: zip(m, g).map { $0 * $1 }, phase: 0, sr: sampleRate)
        let n = Int(seconds * sampleRate)
        var out = [Float](repeating: 0, count: n)
        var block = [Double](repeating: 0, count: blockFrames)
        var b = 0
        while b < n {
            for i in 0..<blockFrames { block[i] = 0 }
            voice.render(into: &block, from: b, sr: sampleRate)
            for i in 0..<min(blockFrames, n - b) { out[b + i] = Float(block[i]) }
            b += blockFrames
        }
        return out
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
        // Every note born up to the lookback before the start may still be sounding.
        nextCell = max(0, Int(((start - Self.lookbackSeconds) / Self.cellSeconds).rounded(.down)))
        block = [Double](repeating: 0, count: Self.blockFrames)
    }

    private func makeVoice(cell: Int) -> Voice? {
        guard let s = Self.strike(seed: seed, cell: cell, warp: warp) else { return nil }
        let f0 = Self.fundamental(seed: seed, cell: cell, warp: s.warp)
        let m = Self.malletAmps(f0: f0)
        let g = Self.gains(seed: seed, cell: cell, amps: m, proportion: s.warp.proportion)
        return Voice(birth: Self.frame(s.birth, sr),
                     f0: f0,
                     warp: s.warp,
                     amps: zip(m, g).map { $0 * $1 },
                     phase: 2 * Double.pi * NightRandom.unit(seed, Self.vibratoPhaseStream, UInt64(cell)),
                     sr: sr)
    }

    /// Renders the absolute block starting at `b` (a multiple of `blockFrames`) into `block`.
    private mutating func renderBlock(_ b: Int) {
        let blockEnd = b + Self.blockFrames
        voices.removeAll { $0.end <= b }
        while Double(nextCell) * Self.cellSeconds * sr <= Double(blockEnd) {
            if let v = makeVoice(cell: nextCell) { voices.append(v) }
            nextCell += 1
        }
        for i in 0..<Self.blockFrames { block[i] = 0 }
        for v in voices where v.birth < blockEnd { v.render(into: &block, from: b, sr: sr) }
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
