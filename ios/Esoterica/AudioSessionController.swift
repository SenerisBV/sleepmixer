import AVFoundation
import MediaPlayer
import NightPlan
import NightRadio

/// The radio's place in iOS audio: the session, interruptions, lost routes, the lock screen.
///
/// - The session is `.playback` with no mixing options, activated when the radio switches on.
/// - A lost route (`.oldDeviceUnavailable`, e.g. headphones pulled) fades out in 0.05 s
///   (`routeLost`, called on the notification's own thread) and the radio stays paused: it never
///   carries on through the phone speaker. A configuration change that lands on the speaker from
///   another output counts as a lost route too, whichever notification arrives first.
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
    /// The output port type when the route last changed; a configuration change that lands on the
    /// speaker from elsewhere is a lost route even if its route-change notification has not arrived.
    private var lastOutput: AVAudioSession.Port? = AudioSessionController.currentOutput()

    /// Paused (by the listener, the lock screen, a lost route or an interruption) while on.
    var isPaused: Bool { on && paused }

    init(engine: RadioEngine) {
        self.engine = engine
        let center = NotificationCenter.default
        let engine = engine
        // Delivered on the posting thread, not hopped to main: iOS has already moved a running engine
        // to the speaker, so the fade starts here. `routeLost()` takes only the engine's control lock.
        observers.append(center.addObserver(forName: AVAudioSession.routeChangeNotification,
                                            object: nil, queue: nil) { [weak self] note in
            let reason = (note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt)
                .flatMap(AVAudioSession.RouteChangeReason.init)
            if reason == .oldDeviceUnavailable { engine.routeLost() }
            let output = Self.currentOutput()
            DispatchQueue.main.async { self?.routeChanged(reason, output: output) }
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
            MainActor.assumeIsolated { self?.configurationChanged() }
        })
        let commands = MPRemoteCommandCenter.shared()
        Self.enableCommands(false)
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
            interruptedWhilePlaying = false
            Self.enableCommands(on)
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

    /// Back from a pause: the session again, the engine again if it stopped, then a fade in.
    func resume() {
        guard on else { return }
        activate()
        engine.restartAfterConfigurationChange()   // no-op while the engine runs
        paused = false
        engine.play()
        publishNowPlaying()
    }

    private func routeChanged(_ reason: AVAudioSession.RouteChangeReason?, output: AVAudioSession.Port?) {
        lastOutput = output
        if reason == .oldDeviceUnavailable { lostRoute() }
    }

    /// The engine already faded (or is fading) out; keep the controller and lock screen in step.
    private func lostRoute() {
        engine.routeLost()                          // idempotent
        guard on else { return }
        paused = true
        interruptedWhilePlaying = false
        publishNowPlaying()
    }

    private func configurationChanged() {
        let output = Self.currentOutput()
        if output == .builtInSpeaker && lastOutput != nil && lastOutput != .builtInSpeaker { lostRoute() }
        lastOutput = output
        engine.restartAfterConfigurationChange()
    }

    nonisolated private static func currentOutput() -> AVAudioSession.Port? {
        AVAudioSession.sharedInstance().currentRoute.outputs.first?.portType
    }

    private static func enableCommands(_ enabled: Bool) {
        let commands = MPRemoteCommandCenter.shared()
        commands.playCommand.isEnabled = enabled
        commands.pauseCommand.isEnabled = enabled
        commands.togglePlayPauseCommand.isEnabled = enabled
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
