"""Standard-library client for a remote visual planner."""

import base64
import json
import os
import urllib.request


class RemotePlanner:
    def __init__(self, url=None, timeout=None):
        self.url = url or os.getenv("VLM_PLANNER_URL", "http://192.168.0.24:8090/plan")
        self.timeout = float(timeout or os.getenv("VLM_PLANNER_TIMEOUT", "60"))
        self.token = os.getenv("VLM_PLANNER_TOKEN", "")

    def plan(self, goal, observation, frame=None):
        body = {"goal": goal, "observation": observation}
        if frame:
            body["image_jpeg"] = base64.b64encode(frame).decode("ascii")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode(),
            method="POST",
            headers=headers,
        )
        print(
            f"[level3:shim] POST {self.url} detections="
            f"{len(observation.get('detections') or [])} frame={bool(frame)}",
            flush=True,
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode())
        if not payload.get("ok", True):
            raise RuntimeError(payload.get("error", "remote planner failed"))
        action = payload.get("action", payload)
        print(f"[level3:shim] action={action}", flush=True)
        return action

    def status(self):
        return {"url": self.url, "timeout": self.timeout}
