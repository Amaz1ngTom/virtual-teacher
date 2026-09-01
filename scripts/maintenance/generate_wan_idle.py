from __future__ import annotations

import argparse
import base64
import csv
import mimetypes
import time
from pathlib import Path

import requests


PROMPT_NO_BLINK = """严格按照输入图片生成，保持人物身份、五官、发型、服装、姿势、画面构图和教室背景完全一致。该视频是几乎静止的虚拟教师待机画面，不是人物表演，不要自行扩展动作。

固定镜头，一位年轻女教师正面面对镜头。人物从第一帧到最后一帧双眼始终自然睁开，瞳孔保持在眼睛中央，目光稳定直视镜头正前方，不闭眼、不眨眼、不眯眼。人物保持输入图片中的温和浅微笑，嘴唇全程自然闭合。

头部、颈部、肩膀、胸口和上半身基本静止，胸口和肩膀没有明显起伏，不表现深呼吸，不改变姿势。只允许极其微弱、几乎无法察觉的自然生命感。镜头、焦距、背景和光线全程固定。结尾平滑回到首帧姿态和表情，适合作为虚拟教师待机循环。

禁止闭眼、视线偏移、张嘴、说话、明显呼吸、胸口起伏、身体晃动、表情变化、镜头运动和背景变化。"""


PROMPT_ONE_BLINK = """严格按照输入图片生成，保持人物身份、五官、发型、服装、姿势、画面构图和教室背景完全一致。该视频是几乎静止的虚拟教师待机画面，不是人物表演，不要自行扩展动作。

固定镜头，一位年轻女教师正面面对镜头。人物双眼自然睁开，瞳孔保持在眼睛中央，目光始终稳定直视镜头正前方。在视频正中间只进行一次快速、轻微、自然的眨眼：双眼同时短暂闭合后立刻完全睁开，眨眼持续时间极短。除这一次快速眨眼外，双眼始终自然睁开并直视镜头，不低头、不转头、不移动视线。

人物保持输入图片中的温和浅微笑，嘴唇全程自然闭合。头部、颈部、肩膀、胸口和上半身基本静止，胸口和肩膀没有明显起伏，不表现深呼吸，不改变姿势。镜头、焦距、背景和光线全程固定。结尾平滑回到首帧姿态和表情，适合作为虚拟教师待机循环。

禁止长时间闭眼，禁止连续眨眼，禁止视线偏移，禁止张嘴、说话、明显呼吸、胸口起伏、身体晃动、表情变化、镜头运动和背景变化。"""


def read_credentials(path: Path) -> tuple[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        values = {
            row[0].strip(): row[1].strip()
            for row in reader
            if len(row) >= 2 and row[0].strip()
        }
    api_key = values.get("apiKey", "")
    workspace_id = values.get("workspaceId", "")
    if not api_key or not workspace_id:
        raise RuntimeError("Credential CSV must contain apiKey and workspaceId")
    return api_key, workspace_id


def image_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def check_response(response: requests.Response) -> dict:
    response.raise_for_status()
    payload = response.json()
    if payload.get("code"):
        raise RuntimeError(
            f"Bailian request failed: {payload['code']}: {payload.get('message', '')}"
        )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a watermark-free virtual-teacher idle video with Wan 3.0."
    )
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=int, choices=range(2, 31), default=5)
    parser.add_argument(
        "--one-blink",
        action="store_true",
        help="Allow exactly one brief blink near the middle of the video.",
    )
    parser.add_argument("--timeout-minutes", type=float, default=20.0)
    args = parser.parse_args()

    credentials = args.credentials.expanduser().resolve()
    image = args.image.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not image.is_file():
        raise FileNotFoundError(image)

    api_key, workspace_id = read_credentials(credentials)
    base_url = f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    frame = image_data_url(image)
    request_body = {
        "model": "wan3.0-video",
        "input": {
            "prompt": PROMPT_ONE_BLINK if args.one_blink else PROMPT_NO_BLINK,
            "media": [
                {"type": "first_frame", "url": frame},
                {"type": "last_frame", "url": frame},
            ],
        },
        "parameters": {
            "resolution": "480P",
            "ratio": "1:1",
            "duration": args.duration,
            "audio": False,
            "prompt_extend": False,
            "watermark": False,
            "seed": 20260827,
        },
    }

    submit_url = f"{base_url}/services/aigc/video-generation/video-synthesis"
    submitted = check_response(
        requests.post(submit_url, headers=headers, json=request_body, timeout=90)
    )
    task_id = submitted.get("output", {}).get("task_id", "")
    if not task_id:
        raise RuntimeError("Bailian did not return a task_id")
    print(f"Submitted task: {task_id}", flush=True)

    deadline = time.monotonic() + args.timeout_minutes * 60
    task_url = f"{base_url}/tasks/{task_id}"
    while True:
        status_payload = check_response(
            requests.get(
                task_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=60,
            )
        )
        task = status_payload.get("output", {})
        status = task.get("task_status", "UNKNOWN")
        print(f"Task status: {status}", flush=True)
        if status == "SUCCEEDED":
            video_url = task.get("video_url", "")
            if not video_url:
                raise RuntimeError("Succeeded task did not return video_url")
            break
        if status in {"FAILED", "CANCELED", "UNKNOWN"}:
            raise RuntimeError(
                f"Video task ended with {status}: "
                f"{task.get('code', '')} {task.get('message', '')}".strip()
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for task {task_id}")
        time.sleep(15)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    with requests.get(video_url, stream=True, timeout=180) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    temporary.replace(output)
    print(f"Saved video: {output}", flush=True)


if __name__ == "__main__":
    main()
