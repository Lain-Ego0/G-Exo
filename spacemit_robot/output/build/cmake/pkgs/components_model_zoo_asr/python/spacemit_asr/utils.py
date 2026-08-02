"""
ASR Utility Functions - Quick and easy recognition
"""

from typing import Union, List, Tuple
from pathlib import Path
import numpy as np

try:
    from . import _spacemit_asr as _asr
except ImportError:
    raise ImportError("_spacemit_asr module not found. Build the C++ bindings first.")

from .engine import Engine, Config, Language


def recognize_file(
    file_path: Union[str, Path],
    language: Language = Language.AUTO,
    model_dir: str = "~/.cache/models/asr/sensevoice",
) -> str:
    """
    Quick recognition of audio file.

    Args:
        file_path: Path to audio file
        language: Recognition language
        model_dir: Path to model directory

    Returns:
        Recognized text

    Example:
        text = recognize_file("audio.wav")
        print(text)
    """
    config = Config(model_dir)
    config.language = language

    with Engine(config) as engine:
        result = engine.recognize_file(file_path)
        return result.text


def recognize_audio(
    audio: np.ndarray,
    sample_rate: int = 16000,
    language: Language = Language.AUTO,
    model_dir: str = "~/.cache/models/asr/sensevoice",
) -> str:
    """
    Quick recognition of audio data.

    Args:
        audio: Audio samples (numpy array)
        sample_rate: Sample rate of audio (will resample if not 16kHz)
        language: Recognition language
        model_dir: Path to model directory

    Returns:
        Recognized text

    Example:
        import numpy as np
        audio = np.random.randn(16000).astype(np.float32)  # 1 second
        text = recognize_audio(audio)
    """
    # Resample if needed
    if sample_rate != 16000:
        from .stream import _resample_linear
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        audio = _resample_linear(audio, sample_rate, 16000)

    config = Config(model_dir)
    config.language = language

    with Engine(config) as engine:
        result = engine.recognize(audio)
        return result.text


def list_devices() -> List[Tuple[int, str]]:
    """
    List available audio input devices.

    Returns:
        List of (device_index, device_name) tuples

    Example:
        devices = list_devices()
        for idx, name in devices:
            print(f"[{idx}] {name}")
    """
    from .stream import AudioStream
    return AudioStream.list_devices()


def get_version() -> str:
    """Get library version"""
    return _asr.ASREngine.get_version()


def get_available_backends() -> list:
    """Get list of available ASR backends"""
    return _asr.ASREngine.get_available_backends()


# Convenience aliases
transcribe = recognize_file
transcribe_audio = recognize_audio
