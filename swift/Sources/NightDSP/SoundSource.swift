/// Fills `out[0..<count]`; requires `out.count >= count`.
public protocol SoundSource {
    mutating func render(into out: inout [Float], count: Int)
}

/// Processes `buffer[0..<count]` in place.
public protocol Processor {
    mutating func process(_ buffer: inout [Float], count: Int)
}
