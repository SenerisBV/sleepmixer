import Foundation

/// Clamp to a range; NaN becomes the range's lower bound.
func clamped(_ v: Double, _ lo: Double, _ hi: Double) -> Double {
    v.isNaN ? lo : min(max(v, lo), hi)
}
