import Foundation

/// Reads PCM int16/int24/int32 or float32 WAV files (mono, or stereo mixed to mono). Foundation only.
/// Understands WAVE_FORMAT_EXTENSIBLE with a PCM or float subformat and skips unknown chunks.
public enum WAVReader {
    public struct Error: Swift.Error, LocalizedError, Equatable {
        public let message: String
        public var errorDescription: String? { message }
    }

    public static func read(url: URL) throws -> (samples: [Float], sampleRate: Double) {
        let d: Data
        do { d = try Data(contentsOf: url) } catch {
            throw Error(message: "cannot read \(url.path): \(error.localizedDescription)")
        }
        let bytes = [UInt8](d)
        func u16(_ o: Int) -> Int { Int(bytes[o]) | Int(bytes[o + 1]) << 8 }
        func u32(_ o: Int) -> Int { u16(o) | u16(o + 2) << 16 }
        guard bytes.count >= 12, String(decoding: bytes[0..<4], as: UTF8.self) == "RIFF",
              String(decoding: bytes[8..<12], as: UTF8.self) == "WAVE" else {
            throw Error(message: "\(url.lastPathComponent) is not a RIFF/WAVE file")
        }
        var format: (tag: Int, channels: Int, rate: Int, bits: Int)?
        var dataRange: Range<Int>?
        var o = 12
        while o + 8 <= bytes.count {
            let id = String(decoding: bytes[o..<(o + 4)], as: UTF8.self)
            let declared = u32(o + 4)
            let body = o + 8
            let size = min(declared, bytes.count - body)   // tolerate truncated / streaming sizes
            if id == "fmt " {
                guard size >= 16 else { throw Error(message: "fmt chunk too short") }
                var tag = u16(body)
                if tag == 0xFFFE {
                    guard size >= 26 else { throw Error(message: "extensible fmt chunk too short") }
                    tag = u16(body + 24)   // first two bytes of the subformat GUID
                }
                format = (tag, u16(body + 2), u32(body + 4), u16(body + 14))
            } else if id == "data" {
                dataRange = body..<(body + size)
                if format != nil { break }
            }
            o = body + size + (size & 1)
        }
        guard let f = format else { throw Error(message: "no fmt chunk") }
        guard let range = dataRange else { throw Error(message: "no data chunk") }
        guard f.channels == 1 || f.channels == 2 else {
            throw Error(message: "unsupported channel count \(f.channels) (mono or stereo only)")
        }
        guard f.rate >= 1000, f.rate <= 384_000 else { throw Error(message: "unsupported sample rate \(f.rate)") }
        let bytesPer = f.bits / 8
        switch (f.tag, f.bits) {
        case (1, 16), (1, 24), (1, 32), (3, 32): break
        default:
            throw Error(message: "unsupported format (tag \(f.tag), \(f.bits)-bit); need PCM 16/24/32-bit or float32")
        }
        let frameBytes = bytesPer * f.channels
        let frames = range.count / frameBytes
        var out = [Float](repeating: 0, count: frames)
        for i in 0..<frames {
            var sum: Float = 0
            for c in 0..<f.channels {
                let p = range.lowerBound + i * frameBytes + c * bytesPer
                let v: Float
                switch (f.tag, f.bits) {
                case (3, _): v = Float(bitPattern: UInt32(truncatingIfNeeded: u32(p)))
                case (_, 16): v = Float(Int16(truncatingIfNeeded: u16(p))) / 32768
                case (_, 24):
                    let raw = Int32(bytes[p]) | Int32(bytes[p + 1]) << 8 | Int32(bytes[p + 2]) << 16
                    v = Float((raw << 8) >> 8) / 8_388_608
                default: v = Float(Int32(truncatingIfNeeded: u32(p))) / 2_147_483_648
                }
                sum += v
            }
            out[i] = sum / Float(f.channels)
        }
        guard out.allSatisfy({ $0.isFinite }) else { throw Error(message: "file contains non-finite samples") }
        return (out, Double(f.rate))
    }
}
