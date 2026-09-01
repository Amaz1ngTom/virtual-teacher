from __future__ import annotations

import argparse
import json

from app.bootstrap import build_runtime, build_tts
from app.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the phase-1 virtual teacher")
    parser.add_argument("--text")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--user-id", default="demo-user")
    parser.add_argument("--thread-id", default="demo-thread")
    parser.add_argument("--lesson-id", default="demo-lesson")
    parser.add_argument(
        "--tts",
        action="store_true",
        help="synthesize each teacher reply and save it as a local WAV file",
    )
    args = parser.parse_args()

    if not args.text and not args.interactive:
        parser.error("provide --text or --interactive")

    settings = Settings.from_env()
    runtime = build_runtime(settings)
    tts = build_tts(settings) if args.tts else None
    try:
        def run_turn(text: str) -> None:
            result = runtime.invoke(
                user_id=args.user_id,
                thread_id=args.thread_id,
                lesson_id=args.lesson_id,
                text=text,
            )
            output = {
                "reply_text": result["response_text"],
                "emotion": result["emotion"],
                "speech_rate": result["speech_rate"],
                "profile": result["profile"],
            }
            if result.get("lesson_phase"):
                output["teaching_state"] = {
                    "lesson_phase": result["lesson_phase"],
                    "concept_index": result.get("concept_index", 0),
                    "attempt_count": result.get("attempt_count", 0),
                    "score": result.get("score", 0),
                    "current_question": result.get("current_question", ""),
                }
            if tts is not None:
                audio = tts.synthesize(
                    result["response_text"],
                    emotion=result["emotion"],
                    speech_rate=result["speech_rate"],
                )
                output["audio"] = {
                    "path": str(audio.audio_path),
                    "provider": audio.provider,
                    "model": audio.model,
                    "voice": audio.voice,
                    "characters": audio.characters,
                    "request_id": audio.request_id,
                }
            print(json.dumps(output, ensure_ascii=False, indent=2))

        if args.text:
            run_turn(args.text)
        if args.interactive:
            print("输入 exit 或 quit 结束。")
            while True:
                text = input("你：").strip()
                if text.lower() in {"exit", "quit"}:
                    break
                if text:
                    run_turn(text)
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
