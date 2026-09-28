// swift-tools-version: 6.1

import PackageDescription

let package = Package(
    name: "SwiftSDKJourney",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/tx3-lang/swift-sdk.git", exact: "0.15.0"),
        .package(name: "DemoClient", path: "__GENERATED__"),
    ],
    targets: [
        .executableTarget(
            name: "SwiftSDKJourney",
            dependencies: [
                .product(name: "Tx3SDK", package: "swift-sdk"),
                .product(name: "DemoClient", package: "DemoClient"),
            ]
        )
    ]
)
