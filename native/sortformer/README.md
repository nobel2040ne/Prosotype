# Weave Streaming Sortformer helper

This Swift 6 executable keeps NVIDIA Streaming Sortformer v2.1 Core ML state
outside the Python 3.11 ASR process. It is pinned to FluidAudio 0.15.5 and runs
only on Apple Silicon; Weave falls back to its ONNX segmentation/embedding
tracker everywhere else.

Prepare it through the repository setup command:

```bash
.venv/bin/python scripts/fetch_streaming_model.py --sortformer-only
```

The persistent process reads newline-delimited JSON from stdin. `audio` carries
base64 little-endian float32 mono/16 kHz samples; `reset`, `finish`, and `close`
control the stream. Stdout contains only JSON timeline events. Audio and model
outputs remain local.

The helper uses NVIDIA's `diar_streaming_sortformer_4spk-v2.1` checkpoint via
FluidAudio's palettized Core ML conversion. Review the upstream NVIDIA Open
Model License and FluidAudio Apache-2.0 license when redistributing weights or
binaries; weights are downloaded into the ignored `assets/sortformer-coreml/`
directory and are not committed.
