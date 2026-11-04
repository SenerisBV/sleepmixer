import AVFoundation
import MediaPlayer
import NightPlan
import NightRadio

/// The radio's place in iOS audio: the session, interruptions, lost routes, the lock screen.
///
/// - The session is `.playback` with no mixing options, activated when the radio switches on.
/// - A lost route (`.oldDeviceUnavailable`, e.g. headphones pulled) pauses, and the radio stays
///   paused: it never carries on through the phone speaker.
/// - `AVAudioEngineConfigurationChange` (the engine stops itself on route and format changes) starts
///   the engine again from silence; while paused it stays silent (`restartAfterConfigurationChange`).
/// - Interruptions: began pauses; ended with `.shouldResume` restarts the engine and plays.
/// - Lock screen play/pause drive `play()` / `pause()`; the title is the station under the needle.
final class AudioSessionController {
    private let engine: RadioEngine
    private var observers: [NSObjectProtocol] = []
    private var paused = false
    /// Paused by an interruption (not by the listener): only then does its end resume.
    private var interruptedWhilePlaying = false
    private var on = false
    private var title: String?

    init(engine: RadioEngine) {
        self.engine = engine
        let center = NotificationCenter.default
        observers.append(center.addObserver(forName: AVAudioSession.routeChangeNotification,
                                            object: nil, queue: .main) { [weak self] note in
            let raw = note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
            MainActor.assumeIsolated { self?.routeChanged(raw.flatMap(AVAudioSession.RouteChangeReason.init)) }
        })
        observers.append(center.addObserver(forName: AVAudioSession.interruptionNotification,
                                            object: nil, queue: .main) { [weak self] note in
            let type = (note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt)
                .flatMap(AVAudioSession.InterruptionType.init)
            let options = (note.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt)
                .map(AVAudioSession.InterruptionOptions.init) ?? []
            MainActor.assumeIsolated { self?.interrupted(type, options) }
        })
        // One engine in the app, private to RadioEngine: any engine's configuration change is ours.
        observers.append(center.addObserver(forName: .AVAudioEngineConfigurationChange,
                                            object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.engine.restartAfterConfigurationChange() }
        })
        let commands = MPRemoteCommandCenter.shared()
        commands.playCommand.addTarget { @Sendable [weak self] _ in
            Task { @MainActor in self?.resume() }
            return .success
        }
        commands.pauseCommand.addTarget { @Sendable [weak self] _ in
            Task { @MainActor in self?.pause() }
            return .success
        }
        commands.togglePlayPauseCommand.addTarget { @Sendable [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                if self.paused { self.resume() } else { self.pause() }
            }
            return .success
        }
    }

    /// Call before the needle leaves the off zone: the engine starts inside `setNeedle`.
    func activate() {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playback, mode: .default, options: [])
            try session.setActive(true)
        } catch {
            NSLog("Esoterica: audio session failed to activate: \(error)")
        }
    }

    /// The needle moved (dragged or snapped): keep the lock screen in step.
    func needleMoved(to needle: Double) {
        let nowOn = Dial.gains(needle: needle, stations: StationRecipe.all).isOn
        if nowOn != on {
            on = nowOn
            paused = false
        }
        let t = Dial.nowPlayingTitle(needle: needle, stations: StationRecipe.all)
        if t != title {
            title = t
            publishNowPlaying()
        }
    }

    private func pause() {
        guard on else { return }
        paused = true
        engine.pause()
        publishNowPlaying()
    }

    private func resume() {
        guard on else { return }
        activate()
        engine.restartAfterConfigurationChange()   // no-op while the engine runs
        paused = false
        engine.play()
        publishNowPlaying()
    }

    private func routeChanged(_ reason: AVAudioSession.RouteChangeReason?) {
        if reason == .oldDeviceUnavailable { pause() }
    }

    private func interrupted(_ type: AVAudioSession.InterruptionType?, _ options: AVAudioSession.InterruptionOptions) {
        switch type {
        case .began:
            interruptedWhilePlaying = on && !paused
            pause()
        case .ended:
            if interruptedWhilePlaying && paused && options.contains(.shouldResume) { resume() }
            interruptedWhilePlaying = false
        default: break
        }
    }

    private func publishNowPlaying() {
        let center = MPNowPlayingInfoCenter.default()
        guard on, let title else {
            center.nowPlayingInfo = nil
            center.playbackState = .stopped
            return
        }
        center.nowPlayingInfo = [
            MPMediaItemPropertyTitle: title,
            MPMediaItemPropertyArtist: "Esoterica DM Radio",
            MPNowPlayingInfoPropertyIsLiveStream: true,
            MPNowPlayingInfoPropertyPlaybackRate: paused ? 0.0 : 1.0,
        ]
        center.playbackState = paused ? .paused : .playing
    }
}
