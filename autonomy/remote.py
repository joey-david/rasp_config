"""Standard-library client for a remote visual planner."""

import base64
import json
import os
import time
import urllib.request


class RemotePlanner:
    def __init__(self, url=None, timeout=None):
        self.url = url or os.getenv("VLM_PLANNER_URL", "http://192.168.0.24:8090/plan")
        self.timeout = float(timeout or os.getenv("VLM_PLANNER_TIMEOUT", "60"))
        self.token = os.getenv("VLM_PLANNER_TOKEN", "")

    def plan(self, goal, observation, frame=None):
        budget = self.timeout
        captured = observation.get("captured_at")
        if captured is not None and "max_age_seconds" in observation:
            budget = min(budget, observation["max_age_seconds"] - (time.time() - captured))
        if budget <= 0:
            raise TimeoutError("planner observation expired")
        body = {"goal": goal, "observation": observation, "timeout_seconds": budget}
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
        with urllib.request.urlopen(request, timeout=budget) as response:
            payload = json.loads(response.read().decode())
        if not payload.get("ok", True):
            raise RuntimeError(payload.get("error", "remote planner failed"))
        action = payload.get("action", payload)
        print(f"[level3:shim] action={action}", flush=True)
        return action

    def status(self):
        return {"url": self.url, "timeout": self.timeout}
