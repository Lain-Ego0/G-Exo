"""
ASR Callback - Base class for streaming recognition callbacks

This module provides the AsrCallback base class that users can subclass
to receive streaming recognition events, similar to the C++ AsrEngineCallback.
"""

from abc import ABC
from typing import Any

try:
    from . import _spacemit_asr as _asr
except ImportError:
    _asr = None


class AsrCallback(ABC):
    """
    Base class for ASR streaming callbacks.

    Subclass this to receive events during streaming recognition.
    This provides a similar interface to the C++ AsrEngineCallback.

    ## Callback Chain (Call Order)

    ```
      start()
         |
         v
      on_open()              <- Session started
         |
         v
      send_audio_frame() --> on_event()  <- Triggered for each result
         |                     |
         |                     +- is_final=False: Intermediate result
         |                     +- is_final=True:  Final result (sentence end)
         v
      stop()
         |
         v
      on_complete()          <- Recognition completed
         |
         v
      on_close()             <- Session closed
    ```

    ## Error Handling

    If an error occurs during recognition:
    ```
      on_open() -> ... -> on_error() -> on_close()
    ```

    ## Thread Safety

    Callbacks may be invoked from a background thread. Ensure your
    implementation is thread-safe if accessing shared resources.

    Example:
        class MyCallback(AsrCallback):
            def on_open(self):
                print("Recognition started")

            def on_event(self, result):
                if result.is_final:
                    print(f"Final: {result.text}")
                else:
                    print(f"Partial: {result.text}", end='\\r')

            def on_complete(self):
                print("Recognition completed")

            def on_error(self, result):
                print(f"Error: {result}")

            def on_close(self):
                print("Session closed")

        # Use with streaming engine
        callback = MyCallback()
        engine.start(callback=callback)
        for chunk in audio_stream:
            engine.send_audio_frame(chunk)
        engine.stop()
    """

    def __init__(self):
        self._native_callback = None

    def on_open(self) -> None:
        """
        Called when recognition session starts.

        Triggered after start() is called.
        """
        pass

    def on_event(self, result: Any) -> None:
        """
        Called when a recognition result is available.

        May be called multiple times during a session:
        - With intermediate results (is_final = False)
        - With final results (is_final = True)

        Args:
            result: Recognition result containing text and metadata
        """
        pass

    def on_complete(self) -> None:
        """
        Called when recognition completes normally.

        Triggered after stop() is called, before on_close().
        """
        pass

    def on_error(self, result: Any) -> None:
        """
        Called when an error occurs.

        After on_error(), on_close() will be called.

        Args:
            result: Result containing error information
        """
        pass

    def on_close(self) -> None:
        """
        Called when the session is closed.

        This is always the last callback, whether the session
        completed normally or with an error.
        """
        pass

    def _get_native_callback(self):
        """Create native C++ callback wrapper for this Python callback."""
        if _asr is None:
            raise ImportError("asr_py module not found")

        if self._native_callback is None:
            self._native_callback = _asr.ASRCallback()
            self._native_callback.on_start(self.on_open)
            self._native_callback.on_result(self.on_event)
            self._native_callback.on_complete(self.on_complete)
            self._native_callback.on_error(lambda e: self.on_error(e))
            self._native_callback.on_close(self.on_close)

        return self._native_callback


class PrintCallback(AsrCallback):
    """
    Simple callback that prints all events to console.

    Useful for debugging and quick testing.

    Example:
        callback = PrintCallback()
    """

    def __init__(self, prefix: str = "[ASR]"):
        """
        Create print callback.

        Args:
            prefix: Prefix for each print statement
        """
        super().__init__()
        self.prefix = prefix

    def on_open(self) -> None:
        print(f"{self.prefix} Session opened")

    def on_event(self, result) -> None:
        status = "Final" if getattr(result, 'is_final', True) else "Partial"
        text = getattr(result, 'text', str(result))
        print(f"{self.prefix} {status}: {text}")

    def on_complete(self) -> None:
        print(f"{self.prefix} Recognition complete")

    def on_error(self, result) -> None:
        text = getattr(result, 'message', str(result))
        print(f"{self.prefix} Error: {text}")

    def on_close(self) -> None:
        print(f"{self.prefix} Session closed")


class CollectCallback(AsrCallback):
    """
    Callback that collects all results into a list.

    Example:
        callback = CollectCallback()
        # ... stream audio ...
        print(callback.results)
        print(callback.get_text())
    """

    def __init__(self):
        super().__init__()
        self.results: list = []
        self.errors: list = []
        self._is_open = False
        self._is_complete = False

    def on_open(self) -> None:
        self._is_open = True
        self.results = []
        self.errors = []

    def on_event(self, result) -> None:
        self.results.append(result)

    def on_complete(self) -> None:
        self._is_complete = True

    def on_error(self, result) -> None:
        self.errors.append(result)

    def on_close(self) -> None:
        self._is_open = False

    def get_text(self) -> str:
        """Get all recognized text concatenated."""
        texts = []
        for r in self.results:
            if hasattr(r, 'is_final') and r.is_final:
                texts.append(r.text)
            elif not hasattr(r, 'is_final'):
                texts.append(r.text)
        return " ".join(texts)

    def get_final_results(self) -> list:
        """Get only final results."""
        return [r for r in self.results if getattr(r, 'is_final', True)]

    @property
    def is_complete(self) -> bool:
        """True if recognition completed normally."""
        return self._is_complete

    @property
    def has_errors(self) -> bool:
        """True if errors occurred."""
        return len(self.errors) > 0
