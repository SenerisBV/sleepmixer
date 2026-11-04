import Synchronization

/// A single-producer, single-consumer ring of mono frames: the render thread writes, the audio
/// callback reads. Lock-free and allocation-free after init: the storage is one preallocated block,
/// and the two positions are monotonic frame counts in `Atomic<Int>` (written with release, read
/// with acquire), so the ring can hold exactly `capacity` frames. Neither side ever blocks: a write
/// takes what fits, a read takes what is there.
///
/// Exactly one thread may write and one may read at a time. `reset()` is only for when neither is
/// running (the engine is stopped and the render thread has finished).
public final class SPSCRing: @unchecked Sendable {
    public let capacity: Int
    private let storage: UnsafeMutablePointer<Float>
    private let written = Atomic<Int>(0)
    private let consumed = Atomic<Int>(0)

    public init(capacity: Int) {
        precondition(capacity > 0)
        self.capacity = capacity
        storage = .allocate(capacity: capacity)
        storage.initialize(repeating: 0, count: capacity)
    }

    deinit { storage.deallocate() }

    /// Frames waiting to be read.
    public var available: Int {
        let r = consumed.load(ordering: .acquiring)
        return written.load(ordering: .acquiring) - r
    }

    /// Frames written since the last reset: the producer's position in the stream.
    public var producedFrames: Int { written.load(ordering: .acquiring) }

    /// Producer side: copies as much of `src` as fits and returns how many frames that was.
    public func write(_ src: UnsafeBufferPointer<Float>) -> Int {
        guard let base = src.baseAddress else { return 0 }
        let w = written.load(ordering: .relaxed)
        let r = consumed.load(ordering: .acquiring)
        let n = min(src.count, capacity - (w - r))
        guard n > 0 else { return 0 }
        let at = w % capacity
        let first = min(n, capacity - at)
        (storage + at).update(from: base, count: first)
        if n > first { storage.update(from: base + first, count: n - first) }
        written.store(w + n, ordering: .releasing)
        return n
    }

    /// Consumer side: copies up to `dst.count` frames into `dst` and returns how many. Never blocks;
    /// frames of `dst` past the returned count are left untouched.
    public func read(into dst: UnsafeMutableBufferPointer<Float>) -> Int {
        guard let base = dst.baseAddress else { return 0 }
        let r = consumed.load(ordering: .relaxed)
        let w = written.load(ordering: .acquiring)
        let n = min(dst.count, w - r)
        guard n > 0 else { return 0 }
        let at = r % capacity
        let first = min(n, capacity - at)
        base.update(from: storage + at, count: first)
        if n > first { (base + first).update(from: storage, count: n - first) }
        consumed.store(r + n, ordering: .releasing)
        return n
    }

    /// Empties the ring. Only while neither side is running.
    func reset() {
        written.store(0, ordering: .sequentiallyConsistent)
        consumed.store(0, ordering: .sequentiallyConsistent)
    }
}
