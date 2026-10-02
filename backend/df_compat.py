"""
Compatibility shim for DeepFilterNet with torchaudio >= 2.11.

torchaudio 2.11+ removed `torchaudio.backend.common.AudioMetaData` and
`torchaudio.info()`, which DeepFilterNet's `df.io` module depends on.

This module patches those back in as lightweight stubs so that
`from df.enhance import init_df, enhance` succeeds.

Usage: import this module BEFORE importing anything from `df`.
"""
import types
import sys

import torchaudio


def _apply_torchaudio_compat():
    """Patch torchaudio to restore removed APIs needed by DeepFilterNet."""

    # 1) Provide torchaudio.backend.common.AudioMetaData
    if not hasattr(torchaudio, "backend") or not hasattr(
        getattr(torchaudio, "backend", None), "common"
    ):
        # Create a minimal AudioMetaData namedtuple-style class
        class AudioMetaData:
            """Minimal stub matching the old torchaudio AudioMetaData."""
            __slots__ = (
                "sample_rate", "num_frames", "num_channels",
                "bits_per_sample", "encoding",
            )

            def __init__(
                self,
                sample_rate: int = 0,
                num_frames: int = 0,
                num_channels: int = 0,
                bits_per_sample: int = 0,
                encoding: str = "",
            ):
                self.sample_rate = sample_rate
                self.num_frames = num_frames
                self.num_channels = num_channels
                self.bits_per_sample = bits_per_sample
                self.encoding = encoding

        # Wire up the module hierarchy: torchaudio.backend.common
        backend_mod = types.ModuleType("torchaudio.backend")
        common_mod = types.ModuleType("torchaudio.backend.common")
        common_mod.AudioMetaData = AudioMetaData

        backend_mod.common = common_mod

        # Register in sys.modules so `from torchaudio.backend.common import …` works
        sys.modules["torchaudio.backend"] = backend_mod
        sys.modules["torchaudio.backend.common"] = common_mod

        # Also attach to the torchaudio package for attribute access
        torchaudio.backend = backend_mod

    # 2) Provide torchaudio.info() if missing
    if not hasattr(torchaudio, "info"):
        import torch
        import wave
        import struct

        def _info_stub(filepath, **kwargs):
            """Minimal torchaudio.info() replacement using wave module."""
            AudioMetaData = sys.modules["torchaudio.backend.common"].AudioMetaData
            try:
                with wave.open(filepath, "rb") as wf:
                    return AudioMetaData(
                        sample_rate=wf.getframerate(),
                        num_frames=wf.getnframes(),
                        num_channels=wf.getnchannels(),
                        bits_per_sample=wf.getsampwidth() * 8,
                        encoding="PCM_S",
                    )
            except Exception:
                # Fallback: load the file to get info
                audio, sr = torchaudio.load(filepath)
                return AudioMetaData(
                    sample_rate=sr,
                    num_frames=audio.shape[-1],
                    num_channels=audio.shape[0],
                    bits_per_sample=16,
                    encoding="PCM_S",
                )

        torchaudio.info = _info_stub


# Apply the patch on import
_apply_torchaudio_compat()
