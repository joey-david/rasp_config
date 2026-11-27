#!/usr/bin/env python3
"""Planner shim from robot observations to one constrained model action."""

import argparse
import base64
import io
import json
import os
import urllib.request

from fastapi import FastAPI, Header, HTTPException
from PIL import Image
from pydantic import BaseModel


SYSTEM = """You plan one step at a time for a small wheeled robot.
Return one JSON object only. It must have an "action" string chosen from
observation.constraints.allowed_actions. Put each listed argument in its own
field. For example, an emote is {"action":"emote","name":"wiggle"}; never use
the action name as a key. Never output motor powers. Relative depth is not
metric. Preserve edge safety, never contact a living being, and avoid fragile
or hazardous objects. Mischief must be harmless, reversible, and proportionate.
Use labels that are actually visible, or use find before acting on an unseen
target."""


class PlanRequest(BaseModel):
    goal: str
    observation: dict
    image_jpeg: str | None = None


class VLM:
    def __init__(self, mock=False):
        self.mock = mock
        self.base_url = os.getenv("VLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
        self.model = os.getenv("VLM_MODEL", "")
        self.api_key = os.getenv("VLM_API_KEY", "")
        self.max_tokens = int(os.getenv("VLM_MAX_TOKENS", "160"))
        self.image_max_side = int(os.getenv("VLM_IMAGE_MAX_SIDE", "320"))

    def _image_url(self, encoded):
        image = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")
        if max(image.size) > self.image_max_side:
            image.thumbnail((self.image_max_side, self.image_max_side))
        output = io.BytesIO()
        image.save(output, "JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode()

    def plan(self, request):
        if self.mock:
            return {"action": "stop", "reason": "mock planner smoke test complete"}
        if not self.model:
            raise RuntimeError("VLM_MODEL is required")
        content = [{"type": "text", "text": json.dumps({
            "goal": request.goal, "observation": request.observation
        }, separators=(",", ":"))}]
        if request.image_jpeg:
            content.append({
                "type": "image_url",
                "image_url": {"url": self._image_url(request.image_jpeg)},
            })
        body = {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": content},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(), method="POST", headers=headers,
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            out = json.loads(response.read().decode())
        content = out["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return json.loads(content)


def create_app(mock=False):
    app, vlm = FastAPI(title="Mischief Bot VLM Planner"), VLM(mock)
    planner_token = os.getenv("VLM_PLANNER_TOKEN", "")

    @app.get("/health")
    def health():
        return {
            "ok": True,
            "mock": vlm.mock,
            "model": vlm.model,
            "base_url": vlm.base_url,
            "image_max_side": vlm.image_max_side,
        }

    @app.post("/plan")
    def plan(request: PlanRequest, authorization: str | None = Header(default=None)):
        if planner_token and authorization != f"Bearer {planner_token}":
            raise HTTPException(status_code=401, detail="invalid planner token")
        try:
            print(
                f"[vlm-server] plan goal={request.goal[:80]!r} detections="
                f"{len(request.observation.get('detections') or [])} image={bool(request.image_jpeg)}",
                flush=True,
            )
            action = vlm.plan(request)
            print(f"[vlm-server] action={action}", flush=True)
            return {"ok": True, "action": action}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(create_app(args.mock), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
