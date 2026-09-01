from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


SUPPORTED_EMOTIONS = {
    "angry",
    "disgust",
    "fear",
    "happy",
    "neutral",
    "sad",
    "surprise",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class WorkerConfig:
    float_root: Path
    checkpoint: Path
    default_reference_image: Path
    audio_roots: List[Path]
    reference_roots: List[Path]
    output_dir: Path
    runtime_dir: Optional[Path] = None
    upload_dir: Optional[Path] = None
    default_nfe: int = 10
    max_upload_bytes: int = 20 * 1024 * 1024

    @property
    def resolved_upload_dir(self) -> Path:
        if self.upload_dir is not None:
            return self.upload_dir
        runtime_dir = self.runtime_dir or (self.output_dir.parent / ".runtime")
        return runtime_dir / "uploads"

    def validate(self) -> List[str]:
        missing = []
        for label, path in (
            ("FLOAT root", self.float_root),
            ("generate.py", self.float_root / "generate.py"),
            ("checkpoint", self.checkpoint),
            ("default reference image", self.default_reference_image),
            ("Wav2Vec2", self.float_root / "checkpoints" / "wav2vec2-base-960h"),
            (
                "emotion encoder",
                self.float_root
                / "checkpoints"
                / "wav2vec-english-speech-emotion-recognition",
            ),
        ):
            if not path.exists():
                missing.append("{}: {}".format(label, path))
        return missing


class RenderRequest(BaseModel):
    audio_path: str = Field(min_length=1)
    reference_image: Optional[str] = None
    emotion: str = "neutral"
    nfe: Optional[int] = Field(default=None, ge=1, le=20)
    seed: int = Field(default=15, ge=0, le=2147483647)
    a_cfg_scale: float = Field(default=2.0, ge=0.0, le=10.0)
    e_cfg_scale: float = Field(default=1.0, ge=0.0, le=10.0)
    no_crop: bool = False


@dataclass
class RenderJob:
    job_id: str
    status: str
    audio_path: str
    reference_image: str
    emotion: str
    nfe: int
    seed: int
    a_cfg_scale: float
    e_cfg_scale: float
    no_crop: bool
    created_at: str
    cleanup_audio: bool = False
    started_at: str = ""
    completed_at: str = ""
    queue_wait_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    total_elapsed_seconds: float = 0.0
    video_path: str = ""
    error: str = ""


class FloatWorkerRuntime:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.state = "created"
        self.load_started_at = ""
        self.load_elapsed_seconds = 0.0
        self.load_error = ""
        self.agent: Any = None
        self.jobs: Dict[str, RenderJob] = {}
        self._jobs_lock = threading.Lock()
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._shutdown = threading.Event()
        self._loader_thread: Optional[threading.Thread] = None
        self._render_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._loader_thread is not None:
            return
        self._configure_runtime_directories()
        self._loader_thread = threading.Thread(
            target=self._load_model,
            name="float-model-loader",
            daemon=True,
        )
        self._loader_thread.start()

    def _configure_runtime_directories(self) -> None:
        """Keep temp/JIT files in a known writable project directory.

        Numba lazily creates cache probe files when librosa first reads audio.
        If the OS temp directory is unavailable, that can look like a stalled
        FLOAT inference while the GPU remains mostly idle.
        """
        runtime_dir = self.config.runtime_dir or (
            self.config.output_dir.parent / ".runtime"
        )
        temp_dir = runtime_dir / "tmp"
        numba_cache_dir = runtime_dir / "numba-cache"
        upload_dir = self.config.resolved_upload_dir
        temp_dir.mkdir(parents=True, exist_ok=True)
        numba_cache_dir.mkdir(parents=True, exist_ok=True)
        upload_dir.mkdir(parents=True, exist_ok=True)
        os.environ["TEMP"] = str(temp_dir)
        os.environ["TMP"] = str(temp_dir)
        os.environ["NUMBA_CACHE_DIR"] = str(numba_cache_dir)
        os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")

    def shutdown(self) -> None:
        self._shutdown.set()
        self._queue.put(None)

    def health(self) -> Dict[str, Any]:
        with self._jobs_lock:
            counts: Dict[str, int] = {}
            for job in self.jobs.values():
                counts[job.status] = counts.get(job.status, 0) + 1
        return {
            "status": self.state,
            "model_loaded": self.agent is not None,
            "load_started_at": self.load_started_at,
            "load_elapsed_seconds": self.load_elapsed_seconds,
            "load_error": self.load_error,
            "queue_size": self._queue.qsize(),
            "jobs": counts,
            "float_root": str(self.config.float_root),
            "output_dir": str(self.config.output_dir),
            "upload_dir": str(self.config.resolved_upload_dir),
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
            "runtime_dir": str(
                self.config.runtime_dir
                or (self.config.output_dir.parent / ".runtime")
            ),
        }

    def _load_model(self) -> None:
        self.state = "loading"
        self.load_started_at = _utc_now()
        started = time.perf_counter()
        try:
            missing = self.config.validate()
            if missing:
                raise FileNotFoundError("Missing FLOAT resources: " + "; ".join(missing))
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
            os.chdir(str(self.config.float_root))
            root_text = str(self.config.float_root)
            if root_text not in sys.path:
                sys.path.insert(0, root_text)

            from generate import InferenceAgent, InferenceOptions

            parser = argparse.ArgumentParser(add_help=False)
            opt = InferenceOptions().initialize(parser).parse_args([])
            opt.pretrained_dir = str(self.config.float_root / "checkpoints")
            opt.wav2vec_model_path = str(
                self.config.float_root / "checkpoints" / "wav2vec2-base-960h"
            )
            opt.audio2emotion_path = str(
                self.config.float_root
                / "checkpoints"
                / "wav2vec-english-speech-emotion-recognition"
            )
            opt.ckpt_path = str(self.config.checkpoint)
            opt.rank = 0
            opt.ngpus = 1
            self.agent = InferenceAgent(opt)
            self.load_elapsed_seconds = round(time.perf_counter() - started, 3)
            self.state = "ready"
            self._render_thread = threading.Thread(
                target=self._consume_jobs,
                name="float-render-queue",
                daemon=True,
            )
            self._render_thread.start()
        except Exception as exc:
            self.load_elapsed_seconds = round(time.perf_counter() - started, 3)
            self.load_error = "{}: {}".format(type(exc).__name__, exc)
            self.state = "error"

    def _validated_file(self, raw_path: str, roots: List[Path], label: str) -> Path:
        path = Path(raw_path).expanduser().resolve()
        allowed = any(_is_within(path, root.resolve()) for root in roots)
        if not allowed:
            raise ValueError("{} is outside allowed roots: {}".format(label, path))
        if not path.is_file():
            raise FileNotFoundError("{} does not exist: {}".format(label, path))
        return path

    def submit(
        self, request: RenderRequest, *, cleanup_audio: bool = False
    ) -> RenderJob:
        if self.state != "ready":
            raise RuntimeError("FLOAT worker is not ready (status={})".format(self.state))
        if request.emotion not in SUPPORTED_EMOTIONS:
            raise ValueError("Unsupported emotion: {}".format(request.emotion))
        audio_roots = list(self.config.audio_roots)
        audio_roots.append(self.config.resolved_upload_dir)
        audio_path = self._validated_file(request.audio_path, audio_roots, "audio_path")
        reference_image = self._validated_file(
            request.reference_image or str(self.config.default_reference_image),
            self.config.reference_roots,
            "reference_image",
        )
        job = RenderJob(
            job_id=uuid.uuid4().hex,
            status="queued",
            audio_path=str(audio_path),
            reference_image=str(reference_image),
            emotion=request.emotion,
            nfe=request.nfe or self.config.default_nfe,
            seed=request.seed,
            a_cfg_scale=request.a_cfg_scale,
            e_cfg_scale=request.e_cfg_scale,
            no_crop=request.no_crop,
            created_at=_utc_now(),
            cleanup_audio=cleanup_audio,
        )
        with self._jobs_lock:
            self.jobs[job.job_id] = job
        self._queue.put(job.job_id)
        return job

    def submit_uploaded_audio(
        self,
        audio: bytes,
        *,
        emotion: str = "neutral",
        nfe: Optional[int] = None,
        seed: int = 15,
        a_cfg_scale: float = 2.0,
        e_cfg_scale: float = 1.0,
        no_crop: bool = False,
    ) -> RenderJob:
        if self.state != "ready":
            raise RuntimeError("FLOAT worker is not ready (status={})".format(self.state))
        if len(audio) < 44:
            raise ValueError("Uploaded WAV is empty or too small")
        if len(audio) > self.config.max_upload_bytes:
            raise ValueError(
                "Uploaded WAV exceeds {} bytes".format(self.config.max_upload_bytes)
            )
        if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise ValueError("Uploaded file is not a RIFF/WAVE audio file")

        upload_dir = self.config.resolved_upload_dir.resolve()
        upload_dir.mkdir(parents=True, exist_ok=True)
        audio_path = (upload_dir / "audio-{}.wav".format(uuid.uuid4().hex)).resolve()
        audio_path.write_bytes(audio)
        try:
            return self.submit(
                RenderRequest(
                    audio_path=str(audio_path),
                    emotion=emotion,
                    nfe=nfe,
                    seed=seed,
                    a_cfg_scale=a_cfg_scale,
                    e_cfg_scale=e_cfg_scale,
                    no_crop=no_crop,
                ),
                cleanup_audio=True,
            )
        except Exception:
            audio_path.unlink(missing_ok=True)
            raise

    def get_job(self, job_id: str) -> Optional[RenderJob]:
        with self._jobs_lock:
            return self.jobs.get(job_id)

    def _consume_jobs(self) -> None:
        while not self._shutdown.is_set():
            job_id = self._queue.get()
            if job_id is None:
                return
            with self._jobs_lock:
                job = self.jobs[job_id]
                job.status = "running"
                job.started_at = _utc_now()
                job.queue_wait_seconds = round(
                    (
                        datetime.now(timezone.utc)
                        - datetime.fromisoformat(job.created_at)
                    ).total_seconds(),
                    3,
                )
            started = time.perf_counter()
            try:
                output_path = (
                    self.config.output_dir / "float-{}.mp4".format(job.job_id)
                ).resolve()
                self.agent.run_inference(
                    str(output_path),
                    job.reference_image,
                    job.audio_path,
                    a_cfg_scale=job.a_cfg_scale,
                    r_cfg_scale=1.0,
                    e_cfg_scale=job.e_cfg_scale,
                    emo=job.emotion,
                    nfe=job.nfe,
                    no_crop=job.no_crop,
                    seed=job.seed,
                    verbose=True,
                )
                if not output_path.is_file():
                    raise RuntimeError("FLOAT did not create the expected video")
                with self._jobs_lock:
                    job.status = "completed"
                    job.video_path = str(output_path)
            except Exception as exc:
                with self._jobs_lock:
                    job.status = "failed"
                    job.error = "{}: {}".format(type(exc).__name__, exc)
            finally:
                with self._jobs_lock:
                    job.elapsed_seconds = round(time.perf_counter() - started, 3)
                    job.completed_at = _utc_now()
                    job.total_elapsed_seconds = round(
                        (
                            datetime.now(timezone.utc)
                            - datetime.fromisoformat(job.created_at)
                        ).total_seconds(),
                        3,
                    )
                if job.cleanup_audio:
                    try:
                        Path(job.audio_path).unlink(missing_ok=True)
                    except OSError:
                        pass

    def completed_video_path(self, job_id: str) -> Path:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError("Unknown FLOAT job")
        if job.status != "completed" or not job.video_path:
            raise RuntimeError("Video is not ready")
        path = Path(job.video_path).resolve()
        if not _is_within(path, self.config.output_dir.resolve()):
            raise ValueError("Video is outside output directory")
        if not path.is_file() or path.suffix.lower() != ".mp4":
            raise FileNotFoundError("Video file is unavailable")
        return path


def create_app(runtime: FloatWorkerRuntime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runtime.start()
        yield
        runtime.shutdown()

    app = FastAPI(title="FLOAT GPU Worker", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return runtime.health()

    @app.post("/v1/jobs", status_code=202)
    def create_job(payload: RenderRequest) -> Dict[str, Any]:
        try:
            return asdict(runtime.submit(payload))
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

    @app.post("/v1/jobs/upload", status_code=202)
    async def create_uploaded_job(
        request: Request,
        emotion: str = "neutral",
        nfe: Optional[int] = Query(default=None, ge=1, le=20),
        seed: int = Query(default=15, ge=0, le=2147483647),
        a_cfg_scale: float = Query(default=2.0, ge=0.0, le=10.0),
        e_cfg_scale: float = Query(default=1.0, ge=0.0, le=10.0),
        no_crop: bool = False,
    ) -> Dict[str, Any]:
        content_length = request.headers.get("content-length", "")
        if content_length.isdigit() and int(content_length) > runtime.config.max_upload_bytes:
            raise HTTPException(status_code=413, detail="Uploaded WAV is too large")
        content_type = request.headers.get("content-type", "").split(";", 1)[0]
        if content_type not in {"audio/wav", "audio/x-wav", "application/octet-stream"}:
            raise HTTPException(status_code=415, detail="Expected a WAV request body")
        audio_buffer = bytearray()
        async for chunk in request.stream():
            audio_buffer.extend(chunk)
            if len(audio_buffer) > runtime.config.max_upload_bytes:
                raise HTTPException(status_code=413, detail="Uploaded WAV is too large")
        audio = bytes(audio_buffer)
        try:
            return asdict(
                runtime.submit_uploaded_audio(
                    audio,
                    emotion=emotion,
                    nfe=nfe,
                    seed=seed,
                    a_cfg_scale=a_cfg_scale,
                    e_cfg_scale=e_cfg_scale,
                    no_crop=no_crop,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str) -> Dict[str, Any]:
        job = runtime.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown FLOAT job")
        return asdict(job)

    @app.get("/v1/jobs/{job_id}/media")
    def get_job_media(job_id: str) -> FileResponse:
        try:
            path = runtime.completed_video_path(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return FileResponse(path, media_type="video/mp4", filename=path.name)

    return app


def _resolve_paths(values: List[str]) -> List[Path]:
    return [Path(value).expanduser().resolve() for value in values]


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run the persistent FLOAT GPU worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--float-root", required=True)
    parser.add_argument(
        "--checkpoint", required=True
    )
    parser.add_argument(
        "--reference-image",
        required=True,
    )
    parser.add_argument(
        "--audio-root",
        action="append",
        default=None,
    )
    parser.add_argument(
        "--reference-root",
        action="append",
        default=None,
    )
    parser.add_argument(
        "--output-dir", default=str(project_root / "outputs" / "video")
    )
    parser.add_argument(
        "--runtime-dir", default=str(project_root / ".runtime")
    )
    parser.add_argument("--upload-dir", default="")
    parser.add_argument("--max-upload-mb", type=int, default=20)
    parser.add_argument("--cuda-visible-devices", default="")
    parser.add_argument("--default-nfe", type=int, default=10)
    args = parser.parse_args()

    if args.cuda_visible_devices:
        # This module intentionally imports FLOAT/torch lazily in _load_model,
        # so the visibility mask is applied before CUDA is initialized.
        os.environ["CUDA_VISIBLE_DEVICES"] = args.cuda_visible_devices

    audio_roots = args.audio_root or [str(project_root / "outputs" / "audio")]
    reference_roots = args.reference_root or [
        str(Path(args.reference_image).resolve().parent),
        str(project_root / "assets"),
    ]

    config = WorkerConfig(
        float_root=Path(args.float_root).expanduser().resolve(),
        checkpoint=Path(args.checkpoint).expanduser().resolve(),
        default_reference_image=Path(args.reference_image).expanduser().resolve(),
        audio_roots=_resolve_paths(audio_roots),
        reference_roots=_resolve_paths(reference_roots),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        runtime_dir=Path(args.runtime_dir).expanduser().resolve(),
        upload_dir=(
            Path(args.upload_dir).expanduser().resolve() if args.upload_dir else None
        ),
        default_nfe=args.default_nfe,
        max_upload_bytes=max(1, args.max_upload_mb) * 1024 * 1024,
    )
    uvicorn.run(
        create_app(FloatWorkerRuntime(config)),
        host=args.host,
        port=args.port,
        timeout_keep_alive=30,
    )


if __name__ == "__main__":
    main()
