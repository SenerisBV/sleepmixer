import Foundation
import NightDSP
import NightPlan

/// The weather outside the radio: the night's window sounds, in stereo.
///
///     rain, stream, crickets: two instances (L and R seeds) -> width mix -> window bus
///     thunder: ONE instance, identical in L and R -> window bus (R3: sudden events keep their
///     documented rate and are never panned to one side; the rumble is near-mono)
///     window bus (not the fire): lowpass ~5 kHz -> + wet short Reverb (small room)
///     fire: ONE instance, centred, its own bus, no lowpass and no reverb
///     (window + fire) x windowGain -> master guard, per channel
///
/// Which sounds play follows the night: rain = rain; rainThunder = rain + thunder;
/// cricketsStream = crickets + stream; fire = fire. Each sound's seeds are fixed by its kind,
/// not by the night, so one seed's rain is the same rain on a rain night and a rainThunder night.
///
/// The window owns no drift clock. Time is seconds since switch-on, which each sound counts from
/// `startSecond` by itself; the sudden sounds (thunder, the fire's pops) read
/// `Weather.sudden(secondsSinceOn:seed:)`, which is a pure function of that time. So the wheel can
/// never bring thunder back: nothing here listens to the dial.
/// Render thread only. Buffers are preallocated; nothing is allocated per block.
public struct WindowChain {
    // MARK: - Placeholders (docs/project-state.md, "Plan 10: the window")

    /// Gain of the whole window, in dB (before the per-night trim). Measured on the rain night
    /// (unit-gain rain is as loud as a station), this puts it about 8.5 dB under a station at drift 0.
    public static let windowGainDB = -17.0
    /// Per-night trims in dB, so every night lands about 8 dB under a station. Raw levels differ:
    /// crickets+stream measure 5.6 dB and the fire 16.1 dB quieter than rain. rainThunder has no
    /// trim, so its rain is bit-identical to a rain night's; a thunder roll lifts it 1-2 dB.
    static let nightTrimDB: [WindowNight: Double] = [.rain: 0, .rainThunder: 0, .cricketsStream: 6.1, .fire: 14.6]
    /// Thunder's own trim in dB (R4): a single centred roll adds coherently in both channels, and at
    /// unit trim its loudest 10 ms came within ~1 dB of the station's; this keeps it 3+ dB under.
    static let thunderTrimDB = -6.0
    static let width = 0.6                // stereo width of the window sounds
    static let lowpassHz = 5000.0         // the open window: nothing bright gets through
    static let reverbWet = 0.2            // the small room's tail, relative to dry
    static let reverbDecaySeconds = 0.4

    /// NightRandom first stream of the sound seeds (60 + kind); Weather.night uses 70.
    static let seedStreamBase: UInt64 = 60
    static let rainK: UInt64 = 0, streamK: UInt64 = 1, cricketsK: UInt64 = 2, thunderK: UInt64 = 3, fireK: UInt64 = 4
    static let reverbSeedL: UInt64 = 0x57494e, reverbSeedR: UInt64 = 0x57494f
    static let initialCapacity = 4096

    /// Width mix: `L' = a*L + b*R`, `R' = a*R + b*L` with `a = cos(phi)`, `b = sin(phi)` and
    /// `phi = asin(1 - w) / 2`. Then `a^2 + b^2 = 1` (power kept for independent L and R) and the
    /// correlation of the pair is `2ab = sin(2 phi) = 1 - w`: w = 1 gives (a, b) = (1, 0), fully
    /// independent; w = 0 gives a = b = 1/sqrt(2), the two channels identical (mono).
    static func mix(width w: Double) -> (a: Float, b: Float) {
        let phi = 0.5 * asin(1 - min(max(w, 0), 1))
        return (Float(cos(phi)), Float(sin(phi)))
    }

    public let night: WindowNight
    /// Test hook: the sounds this night plays.
    var activeSounds: [String] { var s = [String](); if rain != nil { s.append("rain") }
        if thunder != nil { s.append("thunder") }; if crickets != nil { s.append("crickets") }
        if stream != nil { s.append("stream") }; if fire != nil { s.append("fire") }; return s }

    private struct Pair<S: SoundSource> {
        var l: S, r: S
    }
    private var rain: Pair<RainSound>?
    private var stream: Pair<StreamSound>?
    private var crickets: Pair<CricketsSound>?
    private var thunder: ThunderSound?     // one instance, identical in L and R (R3)
    private var fire: FireSound?           // one instance, centred (R3)

    private let windowMix: (a: Float, b: Float)
    private let gain: Float
    private let thunderGain = Float(pow(10, WindowChain.thunderTrimDB / 20))
    private var lowL: Biquad, lowR: Biquad
    private var reverbL: Reverb, reverbR: Reverb
    private var busL: [Float], busR: [Float]       // the window bus
    private var fireL: [Float], fireR: [Float]     // the fire bus
    private var tmpL: [Float], tmpR: [Float]

    public init(seed: UInt64, sampleRate: Double, startSecond: Double = 0, night: WindowNight? = nil) {
        let night = night ?? Weather.night(seed: seed)
        self.night = night
        func s(_ k: UInt64, _ side: UInt64) -> UInt64 { NightRandom.hash(seed, Self.seedStreamBase + k, side) }
        let sudden = Curve<Sudden> { Weather.sudden(secondsSinceOn: $0, seed: seed) }
        func pair<S>(_ k: UInt64, _ make: (UInt64) -> S) -> Pair<S> { Pair(l: make(s(k, 0)), r: make(s(k, 1))) }

        switch night {
        case .rain, .rainThunder:
            rain = pair(Self.rainK) { RainSound(seed: $0, sampleRate: sampleRate, startSecond: startSecond) }
        case .cricketsStream:
            stream = pair(Self.streamK) { StreamSound(seed: $0, sampleRate: sampleRate, startSecond: startSecond) }
            crickets = pair(Self.cricketsK) { CricketsSound(seed: $0, sampleRate: sampleRate, startSecond: startSecond) }
        case .fire:
            fire = FireSound(seed: s(Self.fireK, 0), sampleRate: sampleRate, startSecond: startSecond, sudden: sudden)
        }
        if night == .rainThunder {
            thunder = ThunderSound(seed: s(Self.thunderK, 0), sampleRate: sampleRate, startSecond: startSecond, sudden: sudden)
        }
        windowMix = Self.mix(width: Self.width)
        gain = Float(pow(10, (Self.windowGainDB + (Self.nightTrimDB[night] ?? 0)) / 20))
        lowL = Biquad.lowpass(cutoff: Self.lowpassHz, sampleRate: sampleRate)
        lowR = Biquad.lowpass(cutoff: Self.lowpassHz, sampleRate: sampleRate)
        reverbL = Reverb(sampleRate: sampleRate, seed: NightRandom.hash(seed, Self.seedStreamBase + 5, Self.reverbSeedL))
        reverbR = Reverb(sampleRate: sampleRate, seed: NightRandom.hash(seed, Self.seedStreamBase + 5, Self.reverbSeedR))
        reverbL.decaySeconds = Self.reverbDecaySeconds
        reverbR.decaySeconds = Self.reverbDecaySeconds
        let z = [Float](repeating: 0, count: Self.initialCapacity)
        busL = z; busR = z; fireL = z; fireR = z; tmpL = z; tmpR = z
    }

    /// Adds one stereo pair, width-mixed, onto a bus.
    private static func add<S: SoundSource>(_ p: inout Pair<S>?, mix: (a: Float, b: Float), count: Int,
                                            tmpL: inout [Float], tmpR: inout [Float],
                                            busL: inout [Float], busR: inout [Float]) {
        guard p != nil else { return }
        p!.l.render(into: &tmpL, count: count)
        p!.r.render(into: &tmpR, count: count)
        for i in 0..<count {
            busL[i] += mix.a * tmpL[i] + mix.b * tmpR[i]
            busR[i] += mix.a * tmpR[i] + mix.b * tmpL[i]
        }
    }

    /// Adds one mono sound identically to both buses' channels (thunder, the fire).
    private static func addMono<S: SoundSource>(_ p: inout S?, count: Int, tmp: inout [Float],
                                                busL: inout [Float], busR: inout [Float], gain: Float = 1) {
        guard p != nil else { return }
        p!.render(into: &tmp, count: count)
        for i in 0..<count { busL[i] += gain * tmp[i]; busR[i] += gain * tmp[i] }
    }

    /// Renders `count` frames of stereo into `left[0..<count]` and `right[0..<count]` (overwritten).
    public mutating func render(left: inout [Float], right: inout [Float], count: Int) {
        guard count > 0 else { return }
        if busL.count < count {
            let z = [Float](repeating: 0, count: count)
            busL = z; busR = z; fireL = z; fireR = z; tmpL = z; tmpR = z
        }
        for i in 0..<count { busL[i] = 0; busR[i] = 0; fireL[i] = 0; fireR[i] = 0 }
        Self.add(&rain, mix: windowMix, count: count, tmpL: &tmpL, tmpR: &tmpR, busL: &busL, busR: &busR)
        Self.addMono(&thunder, count: count, tmp: &tmpL, busL: &busL, busR: &busR, gain: thunderGain)
        Self.add(&stream, mix: windowMix, count: count, tmpL: &tmpL, tmpR: &tmpR, busL: &busL, busR: &busR)
        Self.add(&crickets, mix: windowMix, count: count, tmpL: &tmpL, tmpR: &tmpR, busL: &busL, busR: &busR)
        Self.addMono(&fire, count: count, tmp: &tmpL, busL: &fireL, busR: &fireR)

        let wet = Float(Self.reverbWet)
        let hasWindow = fire == nil
        for i in 0..<count {
            var l = fireL[i], r = fireR[i]
            if hasWindow {
                let dl = lowL.process(busL[i]), dr = lowR.process(busR[i])
                l += dl + wet * reverbL.process(dl)
                r += dr + wet * reverbR.process(dr)
            }
            left[i] = NightFactory.masterGuard(l * gain)
            right[i] = NightFactory.masterGuard(r * gain)
        }
    }
}
