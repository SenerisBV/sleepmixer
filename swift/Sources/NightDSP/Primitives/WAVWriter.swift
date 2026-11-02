import Foundation

public enum WAVWriter {
    /// Mono IEEE float32 WAV (format tag 3).
    public static func write(_ samples: [Float], sampleRate: Int, to url: URL) throws {
        var d = Data()
        func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        let dataBytes = UInt32(samples.count * 4)
        d.append(contentsOf: Array("RIFF".utf8)); u32(36 + dataBytes)
        d.append(contentsOf: Array("WAVE".utf8))
        d.append(contentsOf: Array("fmt ".utf8)); u32(16)
        u16(3); u16(1); u32(UInt32(sampleRate)); u32(UInt32(sampleRate * 4)); u16(4); u16(32)
        d.append(contentsOf: Array("data".utf8)); u32(dataBytes)
        for s in samples { u32(s.bitPattern) }
        try d.write(to: url)
    }
}
