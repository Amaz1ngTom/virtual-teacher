"""Portable launchers. Run with the Web Python; FLOAT keeps its own interpreter."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess

from app.config import Settings, resolve_project_path


def worker_command(settings: Settings, port: int) -> list[str]:
    root = settings.project_root
    float_root = resolve_project_path(root, os.getenv("VT_FLOAT_ROOT", "").strip() or "../float-main")
    python = os.getenv("VT_FLOAT_PYTHON", "").strip()
    if python:
        command = [python]
    else:
        conda = os.getenv("CONDA_EXE", "").strip() or shutil.which("conda")
        if not conda:
            raise ValueError("找不到conda，请在 .env 设置 VT_FLOAT_PYTHON 为FLOAT环境的Python路径。")
        command = [conda, "run", "--no-capture-output", "-n", os.getenv("VT_FLOAT_ENV", "FLOAT"), "python"]
    command += [
        str(root / "float_worker" / "server.py"),
        "--float-root", str(float_root), "--checkpoint", str(float_root / "checkpoints" / "float.pth"),
        "--reference-image", str(settings.float_reference_image),
        "--audio-root", str(settings.tts_output_dir),
        "--reference-root", str(settings.float_reference_image.parent),
        "--reference-root", str(root / "assets"), "--reference-root", str(float_root / "assets"),
        "--output-dir", str(root / "outputs" / "video"),
        "--runtime-dir", str(root / ".runtime"), "--host", "127.0.0.1", "--port", str(port),
    ]
    gpu = os.getenv("VT_FLOAT_CUDA_VISIBLE_DEVICES", "").strip()
    if gpu:
        command += ["--cuda-visible-devices", gpu]
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("web", "worker"))
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    settings = Settings.from_env()
    port = args.port if args.port is not None else (8000 if args.mode == "web" else 8011)
    if not 1 <= port <= 65535:
        parser.error("Port must be between 1 and 65535")
    if args.mode == "web":
        if not (settings.project_root / "frontend" / "dist" / "index.html").is_file():
            parser.error("请先在frontend目录执行 npm ci 和 npm run build")
        import uvicorn
        print(f"Virtual Teacher: http://127.0.0.1:{port}", flush=True)
        uvicorn.run("app.api:app", host="127.0.0.1", port=port)
    else:
        if not settings.float_reference_image.is_file():
            parser.error("请提供有权使用的教师图片，并在.env设置 VT_FLOAT_REFERENCE_IMAGE")
        try:
            command = worker_command(settings, port)
        except ValueError as exc:
            parser.error(str(exc))
        raise SystemExit(subprocess.call(command, cwd=settings.project_root))


if __name__ == "__main__":
    main()
