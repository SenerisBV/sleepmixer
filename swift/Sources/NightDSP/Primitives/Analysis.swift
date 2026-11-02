import Foundation

/// Spectral measurements. Buffers shorter than one 4096-sample window yield no spectra:
/// `centroidHz` and both `bandEnergyRatio` variants return 0 for them. Trailing samples that
/// do not fill a window are ignored.
public enum Analysis {
    public static func rmsDB(_ x: ArraySlice<Float>) -> Double {
        guard !x.isEmpty else { return -240 }
        var s = 0.0
        for v in x { s += Double(v) * Double(v) }
        return 10 * log10(max(s / Double(x.count), 1e-24))
    }

    public static func peakDB(_ x: [Float]) -> Double {
        let p = x.reduce(Float(0)) { max($0, abs($1)) }
        return 20 * log10(max(Double(p), 1e-12))
    }

    /// Mean spectral centroid over windows (power-weighted).
    public static func centroidHz(_ x: [Float], sampleRate: Double) -> Double {
        let spectra = powerSpectra(x)
        guard !spectra.isEmpty else { return 0 }
        let binHz = sampleRate / Double(window)
        var total = 0.0
        for p in spectra {
            var num = 0.0, den = 0.0
            for k in 1..<p.count { num += Double(k) * binHz * p[k]; den += p[k] }
            total += den > 0 ? num / den : 0
        }
        return total / Double(spectra.count)
    }

    /// Fraction of total spectral energy at or above `hz`.
    public static func bandEnergyRatio(_ x: [Float], sampleRate: Double, above hz: Double) -> Double {
        ratio(x, sampleRate, hz, above: true)
    }

    /// Fraction of total spectral energy below `hz`.
    public static func bandEnergyRatio(_ x: [Float], sampleRate: Double, below hz: Double) -> Double {
        ratio(x, sampleRate, hz, above: false)
    }

    // MARK: - Spectrum (4096-sample Hann windows, hop 4096, at most 64 spread across the buffer)

    private static let window = 4096
    private static let maxWindows = 64

    private static func ratio(_ x: [Float], _ sr: Double, _ hz: Double, above: Bool) -> Double {
        let binHz = sr / Double(window)
        var hit = 0.0, all = 0.0
        for p in powerSpectra(x) {
            for k in 1..<p.count {
                all += p[k]
                if (Double(k) * binHz >= hz) == above { hit += p[k] }
            }
        }
        return all > 0 ? hit / all : 0
    }

    private static func powerSpectra(_ x: [Float]) -> [[Double]] {
        let count = x.count / window
        guard count > 0 else { return [] }
        let used = min(count, maxWindows)
        let hann = (0..<window).map { 0.5 - 0.5 * cos(2 * Double.pi * Double($0) / Double(window)) }
        return (0..<used).map { w in
            // Spread chosen windows evenly across the buffer.
            let idx = used == count ? w : w * (count - 1) / (used - 1)
            let base = idx * window
            var re = (0..<window).map { Double(x[base + $0]) * hann[$0] }
            var im = [Double](repeating: 0, count: window)
            fft(&re, &im)
            return (0...window / 2).map { re[$0] * re[$0] + im[$0] * im[$0] }
        }
    }

    /// In-place radix-2 FFT; `re.count` must be a power of two.
    private static func fft(_ re: inout [Double], _ im: inout [Double]) {
        let n = re.count
        var j = 0
        for i in 1..<n {
            var bit = n >> 1
            while j & bit != 0 { j ^= bit; bit >>= 1 }
            j ^= bit
            if i < j { re.swapAt(i, j); im.swapAt(i, j) }
        }
        var len = 2
        while len <= n {
            let ang = -2 * Double.pi / Double(len)
            for i in stride(from: 0, to: n, by: len) {
                for k in 0..<len / 2 {
                    let wr = cos(ang * Double(k)), wi = sin(ang * Double(k))
                    let a = i + k, b = i + k + len / 2
                    let tr = re[b] * wr - im[b] * wi, ti = re[b] * wi + im[b] * wr
                    re[b] = re[a] - tr; im[b] = im[a] - ti
                    re[a] += tr; im[a] += ti
                }
            }
            len <<= 1
        }
    }
}
