// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "TradingControl",
    platforms: [.iOS(.v17)],
    products: [
        .library(name: "TradingControl", targets: ["TradingControl"])
    ],
    targets: [
        .target(name: "TradingControl"),
        .testTarget(name: "TradingControlTests", dependencies: ["TradingControl"])
    ]
)
