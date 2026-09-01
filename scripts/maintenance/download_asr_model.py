"""Download only the small INT8 SenseVoice runtime files, never the FP32 model."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import requests

REPOSITORY = "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
MODEL_SHA256 = "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51"
DEFAULT_DIR = Path(__file__).resolve().parents[3] / "models" / "sensevoice-small-int8"


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(destination: Path, samples: bool = False) -> None:
    names = ["model.int8.onnx", "tokens.txt", "LICENSE"]
    if samples:
        names += ["test_wavs/zh.wav", "test_wavs/en.wav"]
    for name in names:
        path = destination / name
        if path.is_file() and path.stat().st_size:
            if name != "model.int8.onnx" or checksum(path) == MODEL_SHA256:
                print(f"Already present: {path}", flush=True)
                continue
            raise RuntimeError(f"Existing model checksum differs: {path}; inspect before replacing")
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix + ".part")
        print(f"Downloading {name} ...", flush=True)
        with requests.get(
            f"https://huggingface.co/{REPOSITORY}/resolve/main/{name}",
            stream=True, timeout=(20, 60),
        ) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    handle.write(chunk)
        if name == "model.int8.onnx" and checksum(partial) != MODEL_SHA256:
            raise RuntimeError("Model checksum mismatch; incomplete file retained as .part")
        partial.replace(path)
        print(f"Saved: {path} ({path.stat().st_size / 1024**2:.1f} MiB)", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--samples", action="store_true", help="Also download two small test WAVs")
    args = parser.parse_args()
    download(args.output_dir.resolve(), args.samples)
