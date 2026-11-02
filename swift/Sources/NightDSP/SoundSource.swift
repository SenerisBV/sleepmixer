import NightPlan

/// Fills `out[0..<count]`; requires `out.count >= count`.
public protocol SoundSource {
    mutating func render(into out: inout [Float], count: Int)
}

/// Processes `buffer[0..<count]` in place.
public protocol Processor {
    mutating func process(_ buffer: inout [Float], count: Int)
}

/// A generator with named elements, deterministic in (seed, absolute time). It starts cold at
/// `startSecond`; `warp` is sampled by absolute second.
public protocol Scene: SoundSource {
    static var kind: SceneKind { get }
    var elements: [String] { get }
    init(seed: UInt64, sampleRate: Double, warp: Curve<WarpDepth>, startSecond: Double)
}
