import Foundation

/// A value that changes over the night, sampled by second.
public struct Curve<Value: Sendable>: Sendable {
    private let at: @Sendable (Double) -> Value

    public init(_ at: @escaping @Sendable (Double) -> Value) { self.at = at }

    public func callAsFunction(_ second: Double) -> Value { at(second) }

    public static func constant(_ v: Value) -> Curve { Curve { _ in v } }
}
