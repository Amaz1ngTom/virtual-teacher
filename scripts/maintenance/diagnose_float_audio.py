"""Measure each FLOAT audio preprocessing stage without loading the video model."""

from __future__ import annotations

import argparse
import faulthandler
import math
import os
import time
import wave
from pathlib import Path

# Configure writable caches before librosa lazily imports Numba modules.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / ".runtime"
TEMP_DIR = RUNTIME_DIR / "tmp"
NUMBA_CACHE_DIR = RUNTIME_DIR / "numba-cache"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
NUMBA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(TEMP_DIR)
os.environ["TMP"] = str(TEMP_DIR)
os.environ["NUMBA_CACHE_DIR"] = str(NUMBA_CACHE_DIR)

import librosa
import numpy as np
from transformers import Wav2Vec2FeatureExtractor


def stamp(start: float, message: str) -> None:
    print(f"[{time.perf_counter() - start:8.3f}s] {message}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", nargs="+")
    parser.add_argument(
        "--wav2vec-path",
        required=True,
        help="Path to the separately installed FLOAT wav2vec2-base-960h checkpoint",
    )
    args = parser.parse_args()

    # Print the exact Python stack if a preprocessing stage stalls.
    faulthandler.dump_traceback_later(20, repeat=True)

    start = time.perf_counter()
    stamp(start, "loading Wav2Vec2 feature extractor")
    extractor = Wav2Vec2FeatureExtractor.from_pretrained(
        args.wav2vec_path, local_files_only=True
    )
    stamp(start, "feature extractor ready")

    for value in args.audio:
        path = Path(value).resolve()
        with wave.open(str(path), "rb") as wav:
            source = (
                f"channels={wav.getnchannels()}, sample_rate={wav.getframerate()}, "
                f"frames={wav.getnframes()}, seconds={wav.getnframes()/wav.getframerate():.3f}"
            )
        stamp(start, f"{path.name}: source {source}")

        item_start = time.perf_counter()
        samples, sample_rate = librosa.load(str(path), sr=16_000, mono=True)
        stamp(
            start,
            f"{path.name}: librosa.load finished in {time.perf_counter()-item_start:.3f}s; "
            f"shape={samples.shape}, sample_rate={sample_rate}",
        )

        item_start = time.perf_counter()
        values = extractor(
            samples, sampling_rate=sample_rate, return_tensors="np"
        ).input_values[0]
        stamp(
            start,
            f"{path.name}: feature extractor finished in {time.perf_counter()-item_start:.3f}s; "
            f"shape={values.shape}, T={math.ceil(values.shape[-1]*25/16_000)}, "
            f"min={values.min():.5f}, max={values.max():.5f}, "
            f"mean={values.mean():.5f}, std={values.std():.5f}, "
            f"finite={bool(np.isfinite(values).all())}",
        )

    faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
