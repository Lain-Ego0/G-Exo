"""
spacemit_vad - SpacemiT VAD Python Package

Usage:
    import spacemit_vad
    result = spacemit_vad.detect(audio_array)
    engine = spacemit_vad.VadEngine()
    callback = spacemit_vad.VadCallback()
"""

from ._spacemit_vad import (
    # Enums
    VadState,
    VadBackendType,
    # Config
    VadConfig,
    # Result
    VadResult,
    # Engine
    VadEngine,
    # Callback
    VadCallback,
    # Quick function
    detect,
    # Module info
    __version__,
)

__all__ = [
    # Enums
    "VadState",
    "VadBackendType",
    # Config
    "VadConfig",
    # Result
    "VadResult",
    # Engine
    "VadEngine",
    # Callback
    "VadCallback",
    # Quick function
    "detect",
    # Module info
    "__version__",
]
