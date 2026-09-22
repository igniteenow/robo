from pathlib import Path

from tools.wake_word import _bundled_wakeword_path


def test_robo_wake_word_resolves_both_packaged_frameworks() -> None:
    onnx = Path(_bundled_wakeword_path("onnx", model_name="hey_roh_boh"))
    tflite = Path(_bundled_wakeword_path("tflite", model_name="hey_roh_boh"))

    assert onnx.name == "hey_roh_boh.onnx"
    assert tflite.name == "hey_roh_boh.tflite"
    assert onnx.is_file()
    assert tflite.is_file()
