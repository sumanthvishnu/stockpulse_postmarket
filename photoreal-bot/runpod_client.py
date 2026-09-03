"""Call the RunPod serverless GPU worker. The Telegram bot has no GPU of its own."""

from __future__ import annotations

import base64
import logging
import os
import time

import requests

log = logging.getLogger("photoreal")

API_KEY = os.environ.get("RUNPOD_API_KEY", "").strip()
ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID", "").strip()
POLL_SEC = 2.5
TIMEOUT_SEC = int(os.environ.get("RUNPOD_TIMEOUT_SEC", "900"))


class WorkerError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    if not API_KEY or not ENDPOINT_ID:
        raise WorkerError(
            "RUNPOD_API_KEY or RUNPOD_ENDPOINT_ID is missing. "
            "Set both in Railway / .env"
        )
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def convert_images(
    photos: list[bytes],
    prompt: str,
    extra: str,
    strength: float,
    on_status=None,
) -> list[bytes]:
    """Send all photos in one GPU job. Returns JPEG bytes, same order."""
    payload = {
        "input": {
            "images": [base64.b64encode(p).decode("ascii") for p in photos],
            "prompt": prompt,
            "extra": extra or "",
            "strength": float(strength),
        }
    }
    start = requests.post(
        f"https://api.runpod.ai/v2/{ENDPOINT_ID}/run",
        headers=_headers(),
        json=payload,
        timeout=60,
    )
    body = start.json() if start.content else {}
    if start.status_code >= 400:
        raise WorkerError(f"RunPod rejected the job: {body or start.text}")
    job_id = body.get("id")
    if not job_id:
        raise WorkerError(f"RunPod did not return a job id: {body}")

    deadline = time.time() + TIMEOUT_SEC
    last_note = ""
    while time.time() < deadline:
        poll = requests.get(
            f"https://api.runpod.ai/v2/{ENDPOINT_ID}/status/{job_id}",
            headers=_headers(),
            timeout=60,
        )
        data = poll.json() if poll.content else {}
        status = (data.get("status") or "").upper()
        note = {
            "IN_QUEUE": "Waiting for a GPU to wake up…",
            "IN_PROGRESS": "GPU is converting your photos…",
        }.get(status, "")
        if note and note != last_note and on_status:
            on_status(note)
            last_note = note

        if status == "COMPLETED":
            output = data.get("output") or {}
            if isinstance(output, dict) and output.get("error"):
                raise WorkerError(str(output["error"]))
            images = output.get("images") if isinstance(output, dict) else None
            if not images:
                raise WorkerError(f"Worker returned no images: {output}")
            return [base64.b64decode(x) for x in images]

        if status in {"FAILED", "CANCELLED", "TIMED_OUT"}:
            raise WorkerError(
                data.get("error")
                or (data.get("output") or {}).get("error")
                or f"RunPod job {status}"
            )
        time.sleep(POLL_SEC)

    raise WorkerError("Timed out waiting for the GPU. Try again in a minute.")
