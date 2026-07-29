import CoreML
import Darwin
import FluidAudio
import Foundation

private struct BridgeCommand: Decodable {
    let type: String
    let audio: String?
    let offset: Double?
}

private struct BridgeSegment: Encodable {
    let speaker: Int
    let start: Double
    let end: Double
    let finalized: Bool
    let activity: Double
}

private struct BridgeEvent: Encodable {
    let type: String
    let processedThrough: Double?
    let latencySeconds: Double?
    let segments: [BridgeSegment]?
    let message: String?
}

private func writeEvent(_ event: BridgeEvent) throws {
    var data = try JSONEncoder().encode(event)
    data.append(0x0A)
    try FileHandle.standardOutput.write(contentsOf: data)
}

private func decodeSamples(_ encoded: String) throws -> [Float] {
    guard let data = Data(base64Encoded: encoded) else {
        throw NSError(
            domain: "AutoCWISortformer",
            code: 2,
            userInfo: [NSLocalizedDescriptionKey: "invalid base64 audio"]
        )
    }
    guard data.count.isMultiple(of: MemoryLayout<Float>.size) else {
        throw NSError(
            domain: "AutoCWISortformer",
            code: 3,
            userInfo: [NSLocalizedDescriptionKey: "misaligned float32 audio"]
        )
    }
    return data.withUnsafeBytes { raw in
        Array(raw.bindMemory(to: Float.self))
    }
}

private func timelineEvent(
    _ diarizer: SortformerDiarizer,
    offset: Double
) -> BridgeEvent {
    let timeline = diarizer.timeline
    var segments: [BridgeSegment] = []
    for (_, speaker) in timeline.speakers.sorted(by: { $0.key < $1.key }) {
        for segment in speaker.finalizedSegments + speaker.tentativeSegments {
            segments.append(
                BridgeSegment(
                    speaker: segment.speakerIndex,
                    start: offset + Double(segment.startTime),
                    end: offset + Double(segment.endTime),
                    finalized: segment.isFinalized,
                    activity: Double(segment.activity)
                )
            )
        }
    }
    segments.sort {
        ($0.start, $0.end, $0.speaker) < ($1.start, $1.end, $1.speaker)
    }
    return BridgeEvent(
        type: "timeline",
        processedThrough: offset + Double(timeline.duration),
        latencySeconds: nil,
        segments: segments,
        message: nil
    )
}

@main
private struct AutoCWISortformer {
    static func main() async {
        do {
            let arguments = Array(CommandLine.arguments.dropFirst())
            let prepareOnly = arguments.contains("--prepare")
            let cachePath: String = {
                guard
                    let index = arguments.firstIndex(of: "--cache"),
                    arguments.indices.contains(index + 1)
                else {
                    return "assets/sortformer-coreml"
                }
                return arguments[index + 1]
            }()

            var config = SortformerConfig.fastV2_1
            // The palettized build was measured at 8.6–8.9x real time on the
            // target Apple Silicon machine while using a fraction of fp16 RAM.
            config.precision = .palettized
            let cacheURL = URL(
                fileURLWithPath: cachePath,
                isDirectory: true
            )
            let models = try await SortformerModels.loadFromHuggingFace(
                config: config,
                cacheDirectory: cacheURL,
                computeUnits: .all
            )
            if prepareOnly {
                try writeEvent(
                    BridgeEvent(
                        type: "prepared",
                        processedThrough: nil,
                        latencySeconds: 1.04,
                        segments: nil,
                        message: cacheURL.path
                    )
                )
                return
            }

            let diarizer = SortformerDiarizer(config: config)
            diarizer.initialize(models: models)
            try writeEvent(
                BridgeEvent(
                    type: "ready",
                    processedThrough: 0,
                    latencySeconds: 1.04,
                    segments: [],
                    message: nil
                )
            )

            var sourceOffset = 0.0
            while let line = readLine(strippingNewline: true) {
                let command = try JSONDecoder().decode(
                    BridgeCommand.self,
                    from: Data(line.utf8)
                )
                switch command.type {
                case "audio":
                    guard let encoded = command.audio else { continue }
                    let samples = try decodeSamples(encoded)
                    if try diarizer.process(
                        samples: samples,
                        sourceSampleRate: 16_000
                    ) != nil {
                        try writeEvent(
                            timelineEvent(diarizer, offset: sourceOffset)
                        )
                    }
                case "reset":
                    diarizer.reset()
                    sourceOffset = command.offset ?? 0
                    try writeEvent(
                        BridgeEvent(
                            type: "reset",
                            processedThrough: sourceOffset,
                            latencySeconds: nil,
                            segments: [],
                            message: nil
                        )
                    )
                case "finish":
                    _ = try diarizer.finalizeSession()
                    try writeEvent(
                        timelineEvent(diarizer, offset: sourceOffset)
                    )
                    try writeEvent(
                        BridgeEvent(
                            type: "finished",
                            processedThrough: sourceOffset
                                + Double(diarizer.timeline.duration),
                            latencySeconds: nil,
                            segments: nil,
                            message: nil
                        )
                    )
                case "close":
                    return
                default:
                    continue
                }
            }
        } catch {
            try? writeEvent(
                BridgeEvent(
                    type: "error",
                    processedThrough: nil,
                    latencySeconds: nil,
                    segments: nil,
                    message: String(describing: error)
                )
            )
            FileHandle.standardError.write(
                Data("[sortformer] \(error)\n".utf8)
            )
            Darwin.exit(1)
        }
    }
}
