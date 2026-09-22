# Hey Roh Boh wake models

Robo bundles the operator-supplied wake-word models unchanged:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `hey_roh_boh.onnx` | 206276 | `CA54D37AC3F7A7479E8166DF08645BAC34A39A42A6BF1BEE81FB0652E2D4461A` |
| `hey_roh_boh.tflite` | 206992 | `C37EAC295EA7A62BB0C31A77631712BE01B7869EAD5B6F5F04B458FFA01910F6` |

The ONNX model is Robo's default openWakeWord model. On Linux, Robo installs
openWakeWord without its unconditional `tflite-runtime` dependency and supplies
the complete ONNX dependency set explicitly. This supports Python 3.13 targets
where no compatible `tflite-runtime` wheel exists. The TFLite model remains
available for compatible embedded integrations.

