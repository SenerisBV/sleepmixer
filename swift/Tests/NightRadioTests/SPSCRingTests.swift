import Testing
@testable import NightRadio

@Suite struct SPSCRingTests {
    @Test func ringRoundTrips() {
        let ring = SPSCRing(capacity: 8192)
        let src = (0..<5000).map { Float($0) * 0.001 - 2 }
        let wrote = src.withUnsafeBufferPointer { ring.write($0) }
        #expect(wrote == 5000)
        #expect(ring.available == 5000)
        var dst = [Float](repeating: 0, count: 5000)
        let read = dst.withUnsafeMutableBufferPointer { ring.read(into: $0) }
        #expect(read == 5000)
        #expect(dst == src)
        #expect(ring.available == 0)
    }

    @Test func ringNeverOverwrites() {
        let ring = SPSCRing(capacity: 1000)
        let src = [Float](repeating: 1, count: 1500)
        #expect(src.withUnsafeBufferPointer { ring.write($0) } == 1000)
        #expect(src.withUnsafeBufferPointer { ring.write($0) } == 0)
        #expect(ring.available == 1000)
    }

    @Test func ringWrapsAround() {
        let ring = SPSCRing(capacity: 1000)
        var dst = [Float](repeating: 0, count: 700)
        for round in 0..<10 {
            let src = (0..<700).map { Float(round * 1000 + $0) }
            #expect(src.withUnsafeBufferPointer { ring.write($0) } == 700)
            #expect(dst.withUnsafeMutableBufferPointer { ring.read(into: $0) } == 700)
            #expect(dst == src)
        }
    }

    @Test func readNeverBlocksWhenShort() {
        let ring = SPSCRing(capacity: 100)
        let src = [Float](repeating: 0.5, count: 30)
        _ = src.withUnsafeBufferPointer { ring.write($0) }
        var dst = [Float](repeating: 9, count: 50)
        #expect(dst.withUnsafeMutableBufferPointer { ring.read(into: $0) } == 30)
        #expect(dst[0..<30].allSatisfy { $0 == 0.5 })
        #expect(dst[30...].allSatisfy { $0 == 9 })      // untouched past what was read
        ring.reset()
        #expect(ring.available == 0)
    }
}
