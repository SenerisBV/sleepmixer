import Foundation
import NightDSP
import NightPlan

/// The spoken word of one station: asks its `StationProgram` what is playing at each block and plays
/// that segment's clip with clip time 0 at the segment's start, then the drift's voice gain and a
/// voice-only `Distance`. Render thread only (it loads files).
///
/// Clips are loaded through the injected loader: the next one when `upcoming` is under
/// `preloadSeconds` away, or at once if a segment starts without a preload (switch-on, or an estimate
/// that moved). At most the current and the next clip are held. A nil load is silence for that
/// segment; the schedule carries on. A segment starting inside a block starts at its exact frame.
/// A clip longer than its scheduled seconds plays out (FileSource fades its end), so nothing is cut.
public struct StationVoice: SoundSource {
    public static let preloadSeconds = 5.0
    static let initialCapacity = 4096

    private struct Loaded { let index: Int; let clip: VoiceClip? }

    private let urls: [URL]
    private let loader: @Sendable (URL) -> VoiceClip?
    private let clock: DriftClock
    private let sampleRate: Double
    private var program: StationProgram
    private var distance: Distance
    private var frame = 0
    private var current: Loaded?
    private var next: Loaded?
    private var playing: ScheduledSegment?
    private var source: FileSource?
    /// When the playing source has nothing left to say (max of the segment end and the clip end).
    private var sourceEnd = 0.0
    private var gain: Double
    private var scratch: [Float]

    public init(bundle: StationBundle, programSeed: UInt64, distanceSeed: UInt64, clock: DriftClock,
                sampleRate: Double, loader: @escaping @Sendable (URL) -> VoiceClip?) {
        urls = bundle.segmentURLs
        self.loader = loader
        self.clock = clock
        self.sampleRate = sampleRate
        program = StationProgram(segmentSeconds: bundle.segmentSeconds, seed: programSeed,
                                 level: { [clock] in clock.level(at: $0) })
        let warp = Curve<WarpDepth> { [clock] in WarpDepth(distance: Drift.voiceDistance(clock.level(at: $0))) }
        distance = Distance(sampleRate: sampleRate, seed: distanceSeed, warp: warp, startSecond: 0)
        gain = Self.linear(Drift.voiceGainDB(clock.level(at: 0)))
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

    public mutating func render(into out: inout [Float], count: Int) {
        guard count > 0 else { return }
        if scratch.count < count { scratch = [Float](repeating: 0, count: count) }
        for i in 0..<count { out[i] = 0 }
        let t0 = Double(frame) / sampleRate
        let tLast = Double(frame + count - 1) / sampleRate

        if let seg = program.segment(at: tLast), seg != playing {
            playing = seg
            let first = min(max(0, Int((seg.start * sampleRate).rounded(.up)) - frame), count - 1)
            if let clip = take(seg.index) {
                let offset = Double(frame + first) / sampleRate - seg.start
                var s = FileSource(samples: clip.samples, fileSampleRate: clip.sampleRate,
                                   sampleRate: sampleRate, startSecond: offset)
                let n = count - first
                s.render(into: &scratch, count: n)
                for i in 0..<n { out[first + i] = scratch[i] }
                source = s
                sourceEnd = max(seg.end, seg.start + Double(clip.samples.count) / clip.sampleRate)
            } else {
                source = nil
            }
        } else if source != nil {
            source!.render(into: &out, count: count)
            if t0 > sourceEnd { source = nil }
        }

        if let up = program.upcoming(after: tLast), up.start - tLast < Self.preloadSeconds,
           next?.index != up.index, current?.index != up.index {
            next = load(up.index)
        }

        let target = Self.linear(Drift.voiceGainDB(clock.level(at: tLast)))
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
