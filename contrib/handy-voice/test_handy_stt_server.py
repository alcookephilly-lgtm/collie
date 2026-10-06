import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from handy_stt_server import create_server


class FakeEngine:
    def __init__(self):
        self.calls = []

    def status(self):
        return {
            "provider": "handy-local-faster-whisper",
            "model": "base",
            "loaded": True,
            "device": "test",
            "dependency_available": True,
        }

    def transcribe(self, path, language=None):
        self.calls.append((path, language))
        return "hello from handy"


def multipart(audio=b"RIFFfake", filename="sample.wav", language="en"):
    boundary = "----handy-test-boundary"
    pieces = [
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="' + filename + '"\r\n'
        "Content-Type: audio/wav\r\n\r\n",
    ]
    body = "".join(pieces).encode() + audio + b"\r\n"
    body += (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="model"\r\n\r\n'
        "base\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="language"\r\n\r\n'
        f"{language}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    return body, f"multipart/form-data; boundary={boundary}"


class HandyServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = FakeEngine()
        cls.server = create_server("127.0.0.1", 0, cls.engine)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, path, method="GET", body=None, content_type=None):
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_health(self):
        status, payload = self.request("/healthz")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["provider"], "handy-local-faster-whisper")
        self.assertEqual(payload["model"], "base")

    def test_openai_compatible_transcription_contract(self):
        body, content_type = multipart()
        status, payload = self.request(
            "/v1/audio/transcriptions", "POST", body, content_type
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"text": "hello from handy"})
        self.assertEqual(self.engine.calls[-1][1], "en")

    def test_rejects_wrong_content_type(self):
        status, payload = self.request(
            "/v1/audio/transcriptions", "POST", b"abc", "audio/wav"
        )
        self.assertEqual(status, 415)
        self.assertIn("multipart", payload["error"])

    def test_rejects_wrong_route(self):
        status, _payload = self.request("/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
