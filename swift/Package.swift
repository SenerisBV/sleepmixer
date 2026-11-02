// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "NightEngine",
    platforms: [.macOS(.v15), .iOS(.v18)],
    products: [
        .library(name: "NightPlan", targets: ["NightPlan"]),
        .library(name: "NightDSP", targets: ["NightDSP"]),
    ],
    dependencies: [
        .package(url: "https://github.com/apple/swift-argument-parser", from: "1.5.0"),
    ],
    targets: [
        .target(name: "NightPlan"),
        .target(name: "NightDSP", dependencies: ["NightPlan"]),
        .target(name: "NightCLI", dependencies: [
            "NightDSP", "NightPlan",
            .product(name: "ArgumentParser", package: "swift-argument-parser"),
        ]),
        .executableTarget(name: "nightctl", dependencies: ["NightCLI"]),
        .testTarget(name: "NightPlanTests", dependencies: ["NightPlan"]),
        .testTarget(name: "NightDSPTests", dependencies: ["NightDSP", "NightPlan"]),
        .testTarget(name: "NightCLITests", dependencies: [
            "NightCLI", "NightDSP", "NightPlan",
            .product(name: "ArgumentParser", package: "swift-argument-parser"),
        ]),
    ]
)
