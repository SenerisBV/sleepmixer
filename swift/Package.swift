// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "NightEngine",
    platforms: [.macOS(.v15), .iOS(.v18)],
    products: [
        .library(name: "NightPlan", targets: ["NightPlan"]),
        .library(name: "NightDSP", targets: ["NightDSP"]),
    ],
    targets: [
        .target(name: "NightPlan"),
        .target(name: "NightDSP", dependencies: ["NightPlan"]),
        .testTarget(name: "NightPlanTests", dependencies: ["NightPlan"]),
    ]
)
