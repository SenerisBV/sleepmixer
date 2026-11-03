import Foundation
import NightDSP
import NightPlan

/// The spoken word of one station: asks its `StationProgram` what is playing at each block and plays
/// that segment's clip, then the drift's voice gain and a voice-only `Distance`. Render thread only
/// (it loads files).
///
/// Where a clip starts:
/// - A segment whose start falls inside the block starts from clip time 0 at its exact frame.
/// - The program reveals a segment only at its next whole-second grid point but backdates `start`
///   (see `StationProgram.advance`), so a segment can appear with a start before this block. It
///   plays from clip time 0 at the block's first frame (the reveal frame) and is never seeked into.
///   Without that, a segment would enter mid-word and lose up to a second whenever the gap is not a
///   whole number of seconds, which is nearly always once drift > 0.
/// - The first segment at switch-on is already under way (the program starts mid-segment). It is
///   seeked to `now − start` and faded in over `fadeInSeconds`, so it never enters at full level.
/// When a new segment replaces a clip that is still sounding (a clip longer than its scheduled
/// seconds), the old one fades out over `fadeOutSeconds`. Nothing starts or stops on a click.
///
/// Clips are loaded through the injected loader: the next one when `upcoming` is under
/// `preloadSeconds` away, or at once if a segment starts without a preload (switch-on, or an estimate
/// that moved). At most the current and the next clip are held. A nil load is silence for that
/// segment; the schedule carries on.
public struct StationVoice: SoundSource {
    public static let preloadSeconds = 5.0
    /// Placeholders (docs/project-state.md, "Plan 9").
    public static let fadeInSeconds = 0.03
    public static let fadeOutSeconds = 0.05
    static let initialCapacity = 4096

    private struct Loaded { let index: Int; let clip: VoiceClip? }

    private let urls: [URL]
    private let loader: @Sendable (URL) -> VoiceClip?
    private let level: @Sendable (Double) -> DriftLevel
    private let sampleRate: Double
    private let fadeInFrames: Int
    private let fadeOutFrames: Int
    private var program: StationProgram
    private var distance: Distance
    private var frame = 0
    private var current: Loaded?
    private var next: Loaded?
    private var playing: ScheduledSegment?
    private var source: FileSource?
    /// Frames of the current block before the source begins (a segment starting mid-block).
    private var sourceDelay = 0
    /// Frames of the switch-on fade-in still to apply (counts up to `fadeInFrames`).
    private var fadeInDone = 0
    private var fadeInActive = false
    /// When the playing source has nothing left to say (max of the segment end and the clip end).
    private var sourceEnd = 0.0
    private var outgoing: FileSource?
    private var fadeOutDone = 0
    private var gain: Double
    private var scratch: [Float]

    public init(bundle: StationBundle, programSeed: UInt64, distanceSeed: UInt64, clock: DriftClock,
                sampleRate: Double, loader: @escaping @Sendable (URL) -> VoiceClip?) {
        self.init(bundle: bundle, programSeed: programSeed, distanceSeed: distanceSeed,
                  level: { [clock] in clock.level(at: $0) }, sampleRate: sampleRate, loader: loader)
    }

    /// The drift as a plain function of engine seconds (tests use a fixed level).
    init(bundle: StationBundle, programSeed: UInt64, distanceSeed: UInt64,
         level: @escaping @Sendable (Double) -> DriftLevel,
         sampleRate: Double, loader: @escaping @Sendable (URL) -> VoiceClip?) {
        urls = bundle.segmentURLs
        self.loader = loader
        self.level = level
        self.sampleRate = sampleRate
        fadeInFrames = max(1, Int((Self.fadeInSeconds * sampleRate).rounded()))
        fadeOutFrames = max(1, Int((Self.fadeOutSeconds * sampleRate).rounded()))
        program = StationProgram(segmentSeconds: bundle.segmentSeconds, seed: programSeed, level: level)
        let warp = Curve<WarpDepth> { WarpDepth(distance: Drift.voiceDistance(level($0))) }
        distance = Distance(sampleRate: sampleRate, seed: distanceSeed, warp: warp, startSecond: 0)
        gain = Self.linear(Drift.voiceGainDB(level(0)))
        scratch = [Float](repeating: 0, count: Self.initialCapacity)
    }

    static func linear(_ db: Double) -> Double { pow(10, db / 20) }

    private func load(_ index: Int) -> Loaded {
        Loaded(index: index, clip: urls.indices.contains(index) ? loader(urls[index]) : nil)
    }

    /// The clip for segment `index`, promoting the preload; drops anything else.
    private mutating func take(_ index: Int) -> VoiceClip? {
        if let n = next, n.index == index {
            current = n
            next = nil
        } else if current?.index != index {
            current = load(index)
        }
        return current?.clip
    }

    private mutating func start(_ seg: ScheduledSegment, t0: Double, count: Int) {
        let switchOn = playing == nil && frame == 0
        playing = seg
        // A clip still sounding is faded out, never cut.
        if let s = source, t0 <= sourceEnd {
            outgoing = s
            fadeOutDone = 0
        }
        source = nil
        let startFrame = Int((seg.start * sampleRate).rounded(.up))
        var delay = 0
        var offset = 0.0
        if startFrame > frame {
            delay = min(startFrame - frame, count - 1)       // starts inside this block
        } else if switchOn {
            offset = max(0, t0 - seg.start)                   // already under way at switch-on
        }                                                     // else: revealed late, play from clip time 0
        guard let clip = take(seg.index) else { return }
        source = FileSource(samples: clip.samples, fileSampleRate: clip.sampleRate,
                            sampleRate: sampleRate, startSecond: offset)
        sourceDelay = delay
        fadeInActive = offset > 0
        fadeInDone = 0
        let clipStart = Double(frame + delay) / sampleRate - offset
        sourceEnd = max(seg.end, clipStart + Double(clip.samples.count) / clip.sampleRate)
    }

    public mutating func render(into out: inout [Float], count: Int) {
        guard count > 0 else { return }
        if scratch.count < count { scratch = [Float](repeating: 0, count: count) }
        for i in 0..<count { out[i] = 0 }
        let t0 = Double(frame) / sampleRate
        let tLast = Double(frame + count - 1) / sampleRate

        if let seg = program.segment(at: tLast), seg != playing {
            start(seg, t0: t0, count: count)
        }

        if outgoing != nil {
            outgoing!.render(into: &scratch, count: count)
            let f = Double(fadeOutFrames)
            for i in 0..<count {
                let k = fadeOutDone + i
                guard k < fadeOutFrames else { break }
                out[i] += scratch[i] * Float(0.5 * (1 + cos(Double.pi * Double(k) / f)))
            }
            fadeOutDone += count
            if fadeOutDone >= fadeOutFrames { outgoing = nil }
        }

        if source != nil {
            let d = sourceDelay
            let n = count - d
            source!.render(into: &scratch, count: n)
            if fadeInActive {
                let f = Double(fadeInFrames)
                for i in 0..<n {
                    let k = fadeInDone + i
                    if k >= fadeInFrames { break }
                    scratch[i] *= Float(0.5 * (1 - cos(Double.pi * Double(k) / f)))
                }
                fadeInDone += n
                if fadeInDone >= fadeInFrames { fadeInActive = false }
            }
            for i in 0..<n { out[d + i] += scratch[i] }
            sourceDelay = 0
            if t0 > sourceEnd { source = nil }
        }

        if let up = program.upcoming(after: tLast), up.start - tLast < Self.preloadSeconds,
           next?.index != up.index, current?.index != up.index {
            next = load(up.index)
        }

        let target = Self.linear(Drift.voiceGainDB(level(tLast)))
        let g0 = gain
        for i in 0..<count {
            let u = Double(i + 1) / Double(count)
            out[i] *= Float(g0 + (target - g0) * u)
        }
        gain = target
        distance.process(&out, count: count)
        frame += count
    }
}
