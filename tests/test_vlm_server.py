import json
import base64
import io
import os
import unittest
from unittest.mock import patch

from PIL import Image

from pc_inference.vlm_server import PlanRequest, VLM


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps({
            "choices": [{"message": {"content": '{"action":"stop"}'}}],
        }).encode()


class PlannerUpstreamContractTests(unittest.TestCase):
    @patch("pc_inference.vlm_server.urllib.request.urlopen", return_value=FakeResponse())
    def test_image_backend_receives_image_and_output_cap(self, urlopen):
        env = {
            "VLM_BASE_URL": "http://127.0.0.1:8000/v1",
            "VLM_MODEL": "local-vlm",
            "VLM_MAX_TOKENS": "160",
        }
        with patch.dict(os.environ, env, clear=True):
            image = Image.new("RGB", (640, 480), "blue")
            encoded = io.BytesIO()
            image.save(encoded, "JPEG")
            action = VLM().plan(PlanRequest(
                goal="stop",
                observation={"detections": [], "constraints": {}},
                image_jpeg=base64.b64encode(encoded.getvalue()).decode(),
            ))

        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(action, {"action": "stop"})
        self.assertIsInstance(body["messages"][1]["content"], list)
        self.assertEqual(len(body["messages"][1]["content"]), 2)
        image_url = body["messages"][1]["content"][1]["image_url"]["url"]
        resized = Image.open(io.BytesIO(base64.b64decode(image_url.split(",", 1)[1])))
        self.assertEqual(resized.size, (320, 240))
        self.assertEqual(body["max_tokens"], 160)


if __name__ == "__main__":
    unittest.main()
