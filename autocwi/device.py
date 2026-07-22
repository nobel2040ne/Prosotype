"""Device selection: cuda -> mps -> cpu. Torch import is lazy so light commands
(fuse, render, --stub runs) never pull in the ML stack."""

from __future__ import annotations


def pick_device(verbose: bool = True) -> str:
    try:
        import torch
    except ImportError:
        if verbose:
            print("[device] torch not installed — cpu (stub/light stages only)")
        return "cpu"

    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    if verbose:
        note = ""
        if device == "mps":
            note = " (note: faster-whisper/CTranslate2 runs on CPU regardless; MPS is used by pyannote)"
        print(f"[device] {device}{note}")
    return device


def seed_everything(seed: int) -> None:
    import random

    import numpy as np

    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
    except ImportError:
        pass
