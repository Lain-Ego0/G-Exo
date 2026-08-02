#!/usr/bin/env python3
"""
SpaceVAD Python Example

Demonstrates basic VAD usage with Python bindings.
"""

import numpy as np

try:
    import spacemit_vad
except ImportError:
    print("Error: spacemit_vad module not found.")
    print("Build and install with:")
    print("  cd vad/build && cmake .. && make && make vad-install-python")
    exit(1)


def generate_audio(sample_rate: int, duration: float, is_speech: bool) -> np.ndarray:
    """Generate test audio (sine wave for speech, noise for silence)."""
    num_samples = int(sample_rate * duration)
    if is_speech:
        freq = 440
        t = np.linspace(0, duration, num_samples, dtype=np.float32)
        return 0.5 * np.sin(2 * np.pi * freq * t).astype(np.float32)
    else:
        return 0.001 * (np.random.rand(num_samples) - 0.5).astype(np.float32)


def main():
    print("=== SpaceVAD Python Example ===")
    print(f"Version: {spacemit_vad.__version__}")
    print()

    # Configuration
    config = spacemit_vad.VadConfig.preset("silero") \
        .with_trigger_threshold(0.5) \
        .with_stop_threshold(0.35)

    print(f"Config: trigger={config.trigger_threshold}, stop={config.stop_threshold}")

    # Create engine
    engine = spacemit_vad.VadEngine(config)
    print(f"Engine: {engine.engine_name}")
    print(f"Initialized: {engine.is_initialized}")
    print()

    if not engine.is_initialized:
        print("Failed to initialize VAD engine!")
        return

    # Test parameters
    sample_rate = 16000
    window_duration = 0.032  # 32ms

    # Test sequence: silence -> speech -> silence
    test_sequence = [
        ("Silence", False),
        ("Silence", False),
        ("Speech", True),
        ("Speech", True),
        ("Speech", True),
        ("Silence", False),
        ("Silence", False),
    ]

    print("Processing test audio frames:")
    print("-" * 50)

    for i, (label, is_speech) in enumerate(test_sequence):
        audio = generate_audio(sample_rate, window_duration, is_speech)
        result = engine.detect(audio, sample_rate)

        state_str = ""
        if result.is_speech_start:
            state_str = " [SPEECH START]"
        elif result.is_speech_end:
            state_str = " [SPEECH END]"

        print(f"Frame {i} ({label}): prob={result.probability:.4f}, "
              f"state={result.state.name}{state_str}")

    print()
    print("=== Streaming Mode Example ===")

    # Create callback
    callback = spacemit_vad.VadCallback()
    callback.on_speech_start(lambda ts: print(f"  -> Speech started at {ts}ms"))
    callback.on_speech_end(lambda ts, dur: print(f"  -> Speech ended at {ts}ms (duration: {dur}ms)"))
    callback.on_event(lambda r: print(f"  Event: prob={r.probability:.4f}"))

    # Reset and start streaming
    engine.reset()
    engine.set_callback(callback)
    engine.start()

    print("Streaming frames...")
    for i, (label, is_speech) in enumerate(test_sequence[:5]):
        audio = generate_audio(sample_rate, window_duration, is_speech)
        engine.send_audio_frame(audio)

    engine.stop()

    print()
    print("=== Quick API Example ===")
    audio = generate_audio(sample_rate, window_duration, True)
    result = spacemit_vad.detect(audio, sample_rate)
    print(f"Quick detect: probability={result.probability:.4f}")

    print()
    print("=== Example Complete ===")


if __name__ == "__main__":
    main()
