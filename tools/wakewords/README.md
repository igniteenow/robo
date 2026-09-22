# Robo wake-word models

`hey_roh_boh.onnx` and `hey_roh_boh.tflite` are the on-device "Hey Roh Boh"
hotword models shipped with Robo. No cloud audio upload or API key is needed
for wake detection.

- Engine: [openWakeWord](https://github.com/dscripka/openWakeWord) (Apache-2.0)
- Model label: `hey_roh_boh`
- Runtime: shared openWakeWord feature-extraction models are downloaded once
  when the wake-word feature is first used

The ONNX model is used on most systems. Robo may select the TFLite model on a
platform where that backend is more reliable.
