"""
ASR Audio Streaming - Real-time audio capture and recognition
"""

from typing import Optional, Callable, Generator, List, Tuple
from threading import Thread, Event
from queue import Queue, Empty
import numpy as np
import time

from .engine import Engine, Config, Result, Language


def _lazy_import_spacemit_audio():
    try:
        import spacemit_audio
        return spacemit_audio
    except ImportError:
        raise ImportError(
            "spacemit_audio package is required for audio streaming features.\n"
            "Install it from: components/multimedia/audio/python/"
        )


def _resample_linear(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or len(samples) < 2:
        return samples
    ratio = dst_rate / src_rate
    n_out = int(len(samples) * ratio)
    indices = np.arange(n_out) / ratio
    idx = np.clip(indices.astype(np.int32), 0, len(samples) - 2)
    frac = (indices - idx).astype(np.float32)
    return samples[idx] * (1 - frac) + samples[idx + 1] * frac


class AudioStream:
    """
    Low-level audio input stream backed by spacemit_audio.AudioCapture.

    Example:
        stream = AudioStream(sample_rate=16000, channels=1)

        def callback(audio, frames, channels):
            print(f"Got {frames} frames")

        stream.set_callback(callback)
        stream.open()
        stream.start()
        time.sleep(5)
        stream.stop()
        stream.close()
    """

    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 2,
        frames_per_buffer: int = 1024,
        device_index: int = -1
    ):
        self._sa = _lazy_import_spacemit_audio()
        self._sample_rate = sample_rate
        self._channels = channels
        self._frames_per_buffer = frames_per_buffer
        self._device_index = device_index
        self._callback = None
        self._capture = None
        self._is_open = False
        self._is_started = False

    def __del__(self):
        try:
            if self._is_open:
                self.stop()
                self.close()
        except Exception:
            pass

    def set_callback(self, callback: Callable[[np.ndarray, int, int], None]):
        self._callback = callback

    def open(self) -> bool:
        try:
            chunk_bytes = self._sample_rate * self._channels * 2 // 25  # ~40ms
            self._sa.init(
                sample_rate=self._sample_rate,
                channels=self._channels,
                chunk_size=chunk_bytes,
                capture_device=self._device_index,
            )
            self._capture = self._sa.AudioCapture()
            if self._callback:
                user_cb = self._callback
                channels = self._channels

                def _bridge(data: bytes):
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                    frames = len(samples) // channels
                    user_cb(samples, frames, channels)

                self._capture.set_callback(_bridge)
            self._is_open = True
            return True
        except Exception:
            return False

    def close(self):
        capture = self._capture
        if capture:
            try:
                capture.stop()
            finally:
                self._capture = None
                self._is_started = False
                self._is_open = False
        else:
            self._is_started = False
            self._is_open = False

    def start(self) -> bool:
        if self._capture:
            self._capture.start()
            self._is_started = True
            return True
        return False

    def stop(self) -> bool:
        if self._capture:
            try:
                self._capture.stop()
            finally:
                self._is_started = False
            return True
        return False

    @property
    def is_running(self) -> bool:
        return self._capture is not None and self._is_started

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    def __enter__(self):
        self.open()
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        self.close()
        return False

    @staticmethod
    def list_devices() -> List[Tuple[int, str]]:
        sa = _lazy_import_spacemit_audio()
        return sa.AudioCapture.list_devices()


class Resampler:
    """Audio resampler using linear interpolation (no C++ dependency)"""

    def __init__(self, input_rate: int, output_rate: int, channels: int = 1):
        self._input_rate = input_rate
        self._output_rate = output_rate
        self._channels = channels

    def process(self, audio: np.ndarray) -> np.ndarray:
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        return _resample_linear(audio, self._input_rate, self._output_rate)


class MicrophoneStream:
    """
    High-level microphone stream with real-time ASR.

    Example:
        with MicrophoneStream() as stream:
            print("Listening... (Ctrl+C to stop)")
            for result in stream.recognize():
                print(f"Recognized: {result.text}")
    """

    def __init__(
        self,
        language: Language = Language.AUTO,
        model_dir: str = "~/.cache/models/asr/sensevoice",
        device_index: int = -1,
        input_sample_rate: int = 48000,
        input_channels: int = 2,
        chunk_duration: float = 5.0,
        frames_per_buffer: int = 2048,
    ):
        self._language = language
        self._model_dir = model_dir
        self._device_index = device_index
        self._input_sample_rate = input_sample_rate
        self._input_channels = input_channels
        self._chunk_duration = chunk_duration
        self._frames_per_buffer = frames_per_buffer

        self._audio_stream: Optional[AudioStream] = None
        self._resampler: Optional[Resampler] = None
        self._engine: Optional[Engine] = None

        self._audio_buffer: List[np.ndarray] = []
        self._result_queue: Queue = Queue()
        self._stop_event = Event()
        self._worker_thread: Optional[Thread] = None
        self._running = False

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def start(self):
        if self._running:
            return

        config = Config(self._model_dir)
        config.language = self._language
        self._engine = Engine(config)
        self._engine.initialize()

        self._audio_stream = AudioStream(
            sample_rate=self._input_sample_rate,
            channels=self._input_channels,
            frames_per_buffer=self._frames_per_buffer,
            device_index=self._device_index
        )

        self._audio_buffer = []
        self._audio_stream.set_callback(self._audio_callback)

        if not self._audio_stream.open():
            raise RuntimeError("Failed to open audio stream")

        actual_sample_rate = self._audio_stream.sample_rate
        if actual_sample_rate != 16000:
            self._resampler = Resampler(actual_sample_rate, 16000, channels=1)
        else:
            self._resampler = None

        if not self._audio_stream.start():
            raise RuntimeError("Failed to start audio stream")

        self._stop_event.clear()
        self._worker_thread = Thread(target=self._recognition_worker, daemon=True)
        self._worker_thread.start()

        self._running = True

    def stop(self):
        if not self._running:
            return

        self._stop_event.set()

        if self._audio_stream:
            self._audio_stream.stop()
            self._audio_stream.close()
            self._audio_stream = None

        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None

        if self._engine:
            self._engine.shutdown()
            self._engine = None

        self._running = False

    def _audio_callback(self, audio: np.ndarray, frames: int, channels: int):
        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1).astype(np.float32)
        else:
            audio = audio.flatten().astype(np.float32)

        if self._resampler:
            audio = self._resampler.process(audio)

        self._audio_buffer.append(audio)

    def _recognition_worker(self):
        target_samples = int(16000 * self._chunk_duration)

        while not self._stop_event.is_set():
            total_samples = sum(len(buf) for buf in self._audio_buffer)

            if total_samples >= target_samples:
                audio = np.concatenate(self._audio_buffer)
                self._audio_buffer = []

                if self._engine and len(audio) > 0:
                    try:
                        result = self._engine.recognize(audio)
                        if result:
                            self._result_queue.put(result)
                    except Exception as e:
                        print(f"Recognition error: {e}")

            time.sleep(0.1)

        if self._audio_buffer and self._engine:
            audio = np.concatenate(self._audio_buffer)
            self._audio_buffer = []
            if len(audio) > 0:
                try:
                    result = self._engine.recognize(audio)
                    if result:
                        self._result_queue.put(result)
                except Exception:
                    pass

    def get_result(self, timeout: Optional[float] = None) -> Optional[Result]:
        try:
            return self._result_queue.get(timeout=timeout)
        except Empty:
            return None

    def recognize(self) -> Generator[Result, None, None]:
        while self._running or not self._result_queue.empty():
            result = self.get_result(timeout=0.5)
            if result:
                yield result

    def listen(self, duration: float = 5.0) -> Optional[Result]:
        """Listen for a fixed duration and return ONE result."""
        was_running = self._running
        if not self._running:
            self._start_recording_only()

        self._audio_buffer = []
        time.sleep(duration)

        if not self._audio_buffer:
            return None

        audio = np.concatenate(self._audio_buffer)
        self._audio_buffer = []

        if not was_running:
            self._stop_recording_only()

        if self._engine and len(audio) > 0:
            try:
                return self._engine.recognize(audio)
            except Exception as e:
                print(f"Recognition error: {e}")
                return None

        return None

    def _start_recording_only(self):
        if self._running:
            return

        if not self._engine:
            config = Config(self._model_dir)
            config.language = self._language
            self._engine = Engine(config)
            self._engine.initialize()

        if not self._audio_stream:
            self._audio_stream = AudioStream(
                sample_rate=self._input_sample_rate,
                channels=self._input_channels,
                frames_per_buffer=self._frames_per_buffer,
                device_index=self._device_index
            )
            self._audio_stream.set_callback(self._audio_callback)

        if not self._audio_stream.is_open:
            if not self._audio_stream.open():
                raise RuntimeError("Failed to open audio stream")

        if not self._resampler:
            actual_sample_rate = self._audio_stream.sample_rate
            if actual_sample_rate != 16000:
                self._resampler = Resampler(actual_sample_rate, 16000, channels=1)

        if not self._audio_stream.is_running:
            if not self._audio_stream.start():
                raise RuntimeError("Failed to start audio stream")

        self._audio_buffer = []
        self._running = True

    def _stop_recording_only(self):
        if self._audio_stream:
            self._audio_stream.stop()
            self._audio_stream.close()
            self._audio_stream = None
        self._running = False

    def close(self):
        self._stop_recording_only()
        if self._engine:
            self._engine.shutdown()
            self._engine = None
        self._resampler = None

    @property
    def is_running(self) -> bool:
        return self._running

    def __enter__(self) -> "MicrophoneStream":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


def list_devices() -> List[Tuple[int, str]]:
    """List available audio input devices."""
    return AudioStream.list_devices()
