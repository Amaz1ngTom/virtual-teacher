from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from float_worker.server import FloatWorkerRuntime, RenderRequest, WorkerConfig


class FloatWorkerRuntimeTests(unittest.TestCase):
    @staticmethod
    def _wav_bytes() -> bytes:
        return b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"\x00" * 32

    def test_submit_rejects_input_outside_allowed_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed_audio = root / "audio"
            allowed_refs = root / "refs"
            allowed_audio.mkdir()
            allowed_refs.mkdir()
            reference = allowed_refs / "teacher.png"
            reference.write_bytes(b"image")
            outside_audio = root / "outside.wav"
            outside_audio.write_bytes(b"audio")
            runtime = FloatWorkerRuntime(
                WorkerConfig(
                    float_root=root,
                    checkpoint=root / "float.pth",
                    default_reference_image=reference,
                    audio_roots=[allowed_audio],
                    reference_roots=[allowed_refs],
                    output_dir=root / "video",
                )
            )
            runtime.state = "ready"

            with self.assertRaises(ValueError):
                runtime.submit(RenderRequest(audio_path=str(outside_audio)))

    def test_submit_queues_valid_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio_root = root / "audio"
            reference_root = root / "refs"
            audio_root.mkdir()
            reference_root.mkdir()
            audio = audio_root / "reply.wav"
            reference = reference_root / "teacher.png"
            audio.write_bytes(b"audio")
            reference.write_bytes(b"image")
            runtime = FloatWorkerRuntime(
                WorkerConfig(
                    float_root=root,
                    checkpoint=root / "float.pth",
                    default_reference_image=reference,
                    audio_roots=[audio_root],
                    reference_roots=[reference_root],
                    output_dir=root / "video",
                    default_nfe=5,
                )
            )
            runtime.state = "ready"

            job = runtime.submit(
                RenderRequest(audio_path=str(audio), emotion="happy")
            )

            self.assertEqual(job.status, "queued")
            self.assertEqual(job.nfe, 5)
            self.assertFalse(job.no_crop)
            self.assertEqual(runtime.health()["queue_size"], 1)

    def test_uploaded_wav_is_queued_in_private_upload_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference_root = root / "refs"
            reference_root.mkdir()
            reference = reference_root / "teacher.png"
            reference.write_bytes(b"image")
            upload_dir = root / "private-inputs"
            runtime = FloatWorkerRuntime(
                WorkerConfig(
                    float_root=root,
                    checkpoint=root / "float.pth",
                    default_reference_image=reference,
                    audio_roots=[],
                    reference_roots=[reference_root],
                    output_dir=root / "video",
                    upload_dir=upload_dir,
                )
            )
            runtime.state = "ready"

            job = runtime.submit_uploaded_audio(
                self._wav_bytes(), emotion="happy"
            )

            uploaded = Path(job.audio_path)
            self.assertTrue(uploaded.is_file())
            self.assertEqual(uploaded.parent, upload_dir.resolve())
            self.assertTrue(job.cleanup_audio)
            self.assertEqual(job.status, "queued")

    def test_upload_rejects_non_wav_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = FloatWorkerRuntime(
                WorkerConfig(
                    float_root=root,
                    checkpoint=root / "float.pth",
                    default_reference_image=root / "teacher.png",
                    audio_roots=[],
                    reference_roots=[root],
                    output_dir=root / "video",
                )
            )
            runtime.state = "ready"

            with self.assertRaisesRegex(ValueError, "RIFF/WAVE"):
                runtime.submit_uploaded_audio(b"not-wave" * 10)

    def test_completed_video_cannot_escape_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio.wav"
            reference = root / "teacher.png"
            audio.write_bytes(b"audio")
            reference.write_bytes(b"image")
            runtime = FloatWorkerRuntime(
                WorkerConfig(
                    float_root=root,
                    checkpoint=root / "float.pth",
                    default_reference_image=reference,
                    audio_roots=[root],
                    reference_roots=[root],
                    output_dir=root / "video",
                )
            )
            runtime.state = "ready"
            job = runtime.submit(RenderRequest(audio_path=str(audio)))
            outside = root / "outside.mp4"
            outside.write_bytes(b"video")
            job.status = "completed"
            job.video_path = str(outside)

            with self.assertRaisesRegex(ValueError, "outside output"):
                runtime.completed_video_path(job.job_id)


if __name__ == "__main__":
    unittest.main()
