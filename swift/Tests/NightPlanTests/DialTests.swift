import Testing
import Foundation
@testable import NightPlan

private let all = StationRecipe.all

@Test func offZoneIsOff() {
    let g = Dial.gains(needle: 0.03, stations: all)
    #expect(g.isOn == false)
    #expect(g.stations == [0, 0, 0])
    #expect(g.staticGain == 0)
}

@Test func onStationIsClean() {
    let g = Dial.gains(needle: 0.25, stations: all)
    #expect(g.isOn)
    #expect(g.stations == [1, 0, 0])
    #expect(g.staticGain == 0)
}

@Test func betweenIsStatic() {
    let g = Dial.gains(needle: 0.40, stations: all)
    #expect(g.stations == [0, 0, 0])
    #expect(g.staticGain == 1)
}

@Test func slightlyOffMixes() {
    let g = Dial.gains(needle: 0.25 + 0.035, stations: all)
    #expect(g.stations[0] > 0 && g.stations[0] < 1)
    #expect(abs(g.staticGain - (1 - g.stations[0])) < 1e-12)
}

@Test func snapsNearStation() {
    #expect(Dial.snapped(0.27, stations: all) == 0.25)
    #expect(Dial.snapped(0.40, stations: all) == 0.40)
    #expect(Dial.snapped(0.03, stations: all) == 0.03)
}

@Test func clampsTravel() {
    let lo = Dial.gains(needle: -1, stations: all)
    #expect(lo.isOn == false)
    let hi = Dial.gains(needle: 2, stations: all)
    #expect(hi.isOn)
    #expect(hi.stations == [0, 0, 0])
    #expect(hi.staticGain == 1)
    #expect(Dial.snapped(2, stations: all) == 1.0)
    #expect(Dial.gains(needle: .nan, stations: all).isOn == false)
}

@Test func detentIndexTicksEveryHundredth() {
    #expect(Dial.detentIndex(0) == 0)
    #expect(Dial.detentIndex(0.0099) == 0)
    #expect(Dial.detentIndex(0.25) == 25)
    #expect(Dial.detentIndex(-3) == 0)
    #expect(Dial.detentIndex(5) == 100)
}
