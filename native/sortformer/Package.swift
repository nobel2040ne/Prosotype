// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "AutoCWISortformer",
    platforms: [
        .macOS(.v14),
    ],
    products: [
        .executable(
            name: "autocwi-sortformer",
            targets: ["AutoCWISortformer"]
        ),
    ],
    dependencies: [
        .package(
            url: "https://github.com/FluidInference/FluidAudio.git",
            exact: "0.15.5"
        ),
    ],
    targets: [
        .executableTarget(
            name: "AutoCWISortformer",
            dependencies: [
                .product(name: "FluidAudio", package: "FluidAudio"),
            ]
        ),
    ]
)
