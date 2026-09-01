from __future__ import annotations

import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from app.models import SUPPORTED_EMOTIONS


@dataclass(frozen=True)
class FloatJobResult:
    job_id: str
    status: str
    video_path: str = ""
    elapsed_seconds: float = 0.0
    queue_wait_seconds: float | None = None
    total_elapsed_seconds: float | None = None
    error: str = ""


class FloatWorkerClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        no_crop: bool = False,
        transfer_mode: str = "path",
        session: Any | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.no_crop = no_crop
        if transfer_mode not in {"path", "upload"}:
            raise ValueError("FLOAT transfer_mode must be 'path' or 'upload'")
        self.transfer_mode = transfer_mode
        self.session = session or requests.Session()

    def _safe_get(self, url: str, *, timeout: float, **kwargs: Any) -> Any:
        """Retry idempotent tunneled GETs after a transient connection reset."""
        last_error: Exception | None = None
        headers = dict(kwargs.pop("headers", {}))
        # Uvicorn and the SSH tunnel can close an idle pooled connection at a
        # keep-alive boundary. A fresh connection is cheap on localhost and
        # avoids repeatedly borrowing a stale socket from requests.Session.
        headers.setdefault("Connection", "close")
        for attempt in range(3):
            try:
                response = self.session.get(
                    url,
                    timeout=timeout,
                    headers=headers,
                    **kwargs,
                )
                response.raise_for_status()
                return response
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.2 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def health(self) -> dict[str, Any]:
        response = self._safe_get(
            f"{self.base_url}/health", timeout=self.timeout_seconds,
        )
        return dict(response.json())

    def submit(
        self,
        *,
        audio_path: Path,
        reference_image: Path,
        emotion: str = "neutral",
        nfe: int | None = None,
    ) -> FloatJobResult:
        emotion = emotion if emotion in SUPPORTED_EMOTIONS else "neutral"
        controls: dict[str, Any] = {
            "emotion": emotion,
            "no_crop": self.no_crop,
        }
        if nfe is not None:
            controls["nfe"] = nfe
        if self.transfer_mode == "upload":
            if not audio_path.is_file():
                raise FileNotFoundError(f"Audio file does not exist: {audio_path}")
            with audio_path.open("rb") as audio:
                response = self.session.post(
                    f"{self.base_url}/v1/jobs/upload",
                    params=controls,
                    data=audio,
                    headers={
                        "Content-Type": "audio/wav",
                        "Connection": "close",
                    },
                    timeout=max(self.timeout_seconds, 30.0),
                )
        else:
            payload = {
                "audio_path": str(audio_path.resolve()),
                "reference_image": str(reference_image.resolve()),
                **controls,
            }
            response = self.session.post(
                f"{self.base_url}/v1/jobs",
                json=payload,
                timeout=self.timeout_seconds,
            )
        response.raise_for_status()
        return self._parse_job(response.json())

    def get_job(self, job_id: str) -> FloatJobResult:
        response = self._safe_get(
            f"{self.base_url}/v1/jobs/{job_id}", timeout=self.timeout_seconds
        )
        return self._parse_job(response.json())

    def wait(
        self,
        job_id: str,
        *,
        poll_seconds: float = 2.0,
        timeout_seconds: float = 900.0,
    ) -> FloatJobResult:
        deadline = time.monotonic() + timeout_seconds
        while True:
            job = self.get_job(job_id)
            if job.status in {"completed", "failed"}:
                return job
            if time.monotonic() >= deadline:
                raise TimeoutError(f"FLOAT job timed out: {job_id}")
            time.sleep(poll_seconds)

    def download_video(self, job_id: str, output_path: Path) -> Path:
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".part")
        response = self._safe_get(
            f"{self.base_url}/v1/jobs/{job_id}/media",
            timeout=max(self.timeout_seconds, 120.0),
            stream=True,
        )
        try:
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise RuntimeError("FLOAT worker returned an empty video")
            temporary.replace(output_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return output_path

    @staticmethod
    def _parse_job(payload: dict[str, Any]) -> FloatJobResult:
        return FloatJobResult(
            job_id=str(payload["job_id"]),
            status=str(payload["status"]),
            video_path=str(payload.get("video_path", "")),
            elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
            queue_wait_seconds=(
                float(payload["queue_wait_seconds"])
                if payload.get("queue_wait_seconds") is not None
                else None
            ),
            total_elapsed_seconds=(
                float(payload["total_elapsed_seconds"])
                if payload.get("total_elapsed_seconds") is not None
                else None
            ),
            error=str(payload.get("error", "")),
        )


class FloatSubprocessRenderer:
    """Compatibility adapter for the existing offline FLOAT CLI.

    The lock prevents multiple requests from competing for the same GPU. This
    adapter reloads FLOAT for every video and is therefore an MVP bridge, not
    the final real-time architecture.
    """

    def __init__(
        self,
        python_executable: Path,
        float_root: Path,
        checkpoint: Path,
        reference_image: Path,
        output_dir: Path,
        timeout_seconds: int = 900,
        no_crop: bool = False,
    ):
        self.python_executable = python_executable
        self.float_root = float_root
        self.checkpoint = checkpoint
        self.reference_image = reference_image
        self.output_dir = output_dir
        self.timeout_seconds = timeout_seconds
        self.no_crop = no_crop
        self._gpu_lock = threading.Lock()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def validate(self) -> list[str]:
        missing = []
        for label, path in (
            ("FLOAT python", self.python_executable),
            ("FLOAT root", self.float_root),
            ("FLOAT generate.py", self.float_root / "generate.py"),
            ("FLOAT checkpoint", self.checkpoint),
            ("reference image", self.reference_image),
        ):
            if not path.exists():
                missing.append(f"{label}: {path}")
        return missing

    def render(self, audio_path: Path, emotion: str = "neutral") -> Path:
        missing = self.validate()
        if missing:
            raise FileNotFoundError("Missing FLOAT resources: " + "; ".join(missing))
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file does not exist: {audio_path}")
        emotion = emotion if emotion in SUPPORTED_EMOTIONS else "neutral"
        output_path = (self.output_dir / f"float-{uuid.uuid4().hex}.mp4").resolve()
        command = [
            str(self.python_executable),
            "generate.py",
            "--ref_path",
            str(self.reference_image),
            "--aud_path",
            str(audio_path),
            "--emo",
            emotion,
            "--seed",
            "15",
            "--a_cfg_scale",
            "2",
            "--e_cfg_scale",
            "1",
            "--ckpt_path",
            str(self.checkpoint),
            "--res_video_path",
            str(output_path),
        ]
        if self.no_crop:
            command.append("--no_crop")
        with self._gpu_lock:
            result = subprocess.run(
                command,
                cwd=self.float_root,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self.timeout_seconds,
            )
        if result.returncode != 0 or not output_path.exists():
            raise RuntimeError(
                "FLOAT failed. stdout:\n"
                + result.stdout[-4000:]
                + "\nstderr:\n"
                + result.stderr[-4000:]
            )
        return output_path
