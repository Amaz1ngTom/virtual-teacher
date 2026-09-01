"""Export an allowlisted source snapshot, never the private development history."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import re
import shutil
import tempfile
import zipfile


ROOT_FILES = {
    "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "SECURITY.md",
    ".gitignore", ".gitattributes", ".env.example", "requirements.txt", "requirements-rag.txt",
    "requirements-asr.txt",
}
DOC_FILES = {
    "architecture.md", "asr.md", "course-builder.md", "environment.md",
    "github-about.md", "performance-results.md", "rag.md", "release-checklist.md",
}
SCRIPT_FILES = {
    "README.md", "launch.bat", "local.settings.example.bat",
    "start_remote_float_session.ps1",
    "no_float/README.md", "no_float/01_start_web.bat",
    "local_float/README.md", "local_float/01_start_worker.bat", "local_float/02_start_web.bat",
    "remote_float/README.md", "remote_float/01_start_session.ps1",
    "remote_float/02_start_web.bat", "remote_float/03_stop_worker.ps1",
    "maintenance/README.md", "maintenance/build_remote_worker_bundle.ps1",
    "maintenance/diagnose_float_audio.py", "maintenance/download_asr_model.py",
    "maintenance/generate_wan_idle.py", "maintenance/split_pdf_by_bookmarks.py",
    "maintenance/run_release_checks.ps1", "maintenance/export_github_source.py",
}
FRONTEND_FILES = {
    ".gitignore", "README.md", "package.json", "package-lock.json", "index.html",
    "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json", "vite.config.ts",
    ".oxlintrc.json", "public/pcm-recorder.js", "tests/audio-recorder.test.mjs",
    "tests/asr-browser.cjs",
}
ASSET_FILES = {
    "README.md", "example/teacher.svg", "teacher/real-teacher-002.png",
    "teacher/real-teacher-002-float-aligned.png",
}
DEPLOY_FILES = {
    "README.md", "requirements.txt", "worker.env.example", "config.sh",
    "run_worker.sh", "start_worker.sh", "stop_worker.sh", "check_worker.sh",
}
REQUIRED_FILES = {
    "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", ".env.example",
    "requirements.txt", "app/api.py", "frontend/package-lock.json",
    "assets/teacher/real-teacher-002.png", "assets/teacher/real-teacher-002-float-aligned.png",
}

# Do not include the matched credential in error output.
SECRET_PATTERNS = [
    ("possible API key", re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}")),
    ("possible AWS key", re.compile(rb"\bAKIA[A-Z0-9]{16}\b")),
    ("private key", re.compile(b"-----BEGIN " + rb"(?:OPENSSH |RSA |EC )?PRIVATE KEY-----")),
    ("personal Windows path", re.compile(rb"[A-Za-z]:[/\\]Users[/\\](?!Public\b)[^\s/\\]+", re.I)),
    ("private LAN address", re.compile(rb"\b172\.18\.\d{1,3}\.\d{1,3}\b")),
]


def selected_files(root: Path) -> list[Path]:
    root = root.resolve()
    candidates = {root / name for name in ROOT_FILES}
    for folder, names in (
        ("docs", DOC_FILES), ("scripts", SCRIPT_FILES), ("frontend", FRONTEND_FILES),
        ("assets", ASSET_FILES), ("deploy/remote_float_worker", DEPLOY_FILES),
    ):
        candidates.update(root / folder / name for name in names)
    for folder, suffixes in (
        ("app", {".py"}), ("tests", {".py"}), ("float_worker", {".py"}),
        ("frontend/src", {".ts", ".tsx", ".css", ".svg"}),
    ):
        candidates.update(
            p for p in (root / folder).rglob("*")
            if p.suffix in suffixes and "__pycache__" not in p.parts
        )
    files = []
    for path in sorted(candidates):
        if not path.is_file():
            continue
        if path.is_symlink() or any(
            p.is_symlink() for p in path.parents if p != root and p.is_relative_to(root)
        ):
            raise ValueError(f"Symlink not allowed: {path.relative_to(root)}")
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"File escapes project root: {path.relative_to(root)}")
        files.append(path)
    return files


def scan_files(root: Path, files: list[Path]) -> list[str]:
    findings = []
    for path in files:
        contents = path.read_bytes()
        # PNG text chunks are uncompressed in these source portraits; also scan their raw bytes.
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(contents):
                findings.append(f"{path.relative_to(root).as_posix()}: {label}")
        if len(contents) > 10 * 1024 * 1024:
            findings.append(f"{path.relative_to(root).as_posix()}: unexpectedly large source file")
    return findings


def check_source(root: Path, *, require_complete: bool = True) -> list[Path]:
    root = root.resolve()
    files = selected_files(root)
    if require_complete:
        missing = REQUIRED_FILES - {p.relative_to(root).as_posix() for p in files}
        if missing:
            raise ValueError("Required release files missing: " + ", ".join(sorted(missing)))
    findings = scan_files(root, files)
    if findings:
        raise ValueError("Release scan requires review:\n" + "\n".join(findings))
    return files


def export_source(root: Path, *, require_complete: bool = True) -> tuple[Path, Path]:
    root = root.resolve()
    files = check_source(root, require_complete=require_complete)
    dist = root / "dist"
    if dist.is_symlink() or not dist.resolve().is_relative_to(root):
        raise ValueError("dist must stay inside project root")
    dist.mkdir(exist_ok=True)
    prefix = "github-source-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-"
    target = Path(tempfile.mkdtemp(prefix=prefix, dir=dist))
    manifest = []
    for path in files:
        relative = path.relative_to(root)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        manifest.append(f"{digest}  {relative.as_posix()}")
    (target / "SOURCE_MANIFEST.sha256").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    archive = target.with_suffix(".zip")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for path in sorted(target.rglob("*")):
            if path.is_file():
                zip_file.write(path, (Path(target.name) / path.relative_to(target)).as_posix())
    return target, archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Scan without creating a snapshot")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        files = check_source(root)
        print(f"[ok] {len(files)} allowlisted source files; automatic scan found no matching patterns.")
        if not args.check:
            target, archive = export_source(root)
            print(f"Source folder: {target}")
            print(f"Source ZIP: {archive}")
            print("No private Git history, environments, weights, textbooks or runtime data exported.")
    except ValueError as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
