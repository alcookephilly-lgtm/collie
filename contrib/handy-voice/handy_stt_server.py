#!/usr/bin/env python3
"""Local OpenAI-compatible STT endpoint backed by Handy/Hermes faster-whisper.

Binds to loopback only. Audio never leaves this machine.
"""
from __future__ import annotations

import argparse
import cgi
import importlib.util
import io
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

MAX_AUDIO_BYTES = 8 * 1024 * 1024
DEFAULT_MODEL = os.getenv("HANDY_STT_MODEL", "base")
CUDA_MARKERS = (
    "cublas",
    "cudnn",
    "cuda",
    "nvcuda",
    "libcublas",
    "libcudnn",
)


class HandyWhisperEngine:
    """Persistent faster-whisper engine; model is loaded once and reused."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model = None
        self._device = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _new_model(self, *, cpu: bool = False):
        from faster_whisper import WhisperModel

        if cpu:
            self._device = "cpu-int8"
            return WhisperModel(self.model_name, device="cpu", compute_type="int8")

        try:
            model = WhisperModel(self.model_name, device="auto", compute_type="auto")
            self._device = "auto"
            return model
        except Exception as exc:
            if not self._looks_like_cuda_error(exc):
                raise
            self._device = "cpu-int8"
            return WhisperModel(self.model_name, device="cpu", compute_type="int8")

    @staticmethod
    def _looks_like_cuda_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(marker in text for marker in CUDA_MARKERS)

    def _ensure_model(self):
        if self._model is None:
            self._model = self._new_model()
        return self._model

    def transcribe(self, path: str, language: Optional[str] = None) -> str:
        # Serialize use of one model instance. Collie already bounds concurrent STT.
        with self._lock:
            model = self._ensure_model()
            kwargs = {"beam_size": 5}
            if language:
                kwargs["language"] = language
            try:
                segments, _info = model.transcribe(path, **kwargs)
                return " ".join(segment.text.strip() for segment in segments).strip()
            except Exception as exc:
                if not self._looks_like_cuda_error(exc):
                    raise
                # Match Hermes' own recovery path: discard a bad CUDA instance and retry on CPU.
                self._model = self._new_model(cpu=True)
                segments, _info = self._model.transcribe(path, **kwargs)
                return " ".join(segment.text.strip() for segment in segments).strip()

    def status(self) -> dict:
        return {
            "provider": "handy-local-faster-whisper",
            "model": self.model_name,
            "loaded": self.loaded,
            "device": self._device,
            "dependency_available": importlib.util.find_spec("faster_whisper") is not None,
        }


def _json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("content-length", str(len(body)))
    handler.send_header("cache-control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".wav", ".webm", ".ogg", ".mp4", ".m4a", ".mp3", ".mpeg", ".aac", ".flac"}:
        return suffix
    return ".audio"


def make_handler(engine):
    class HandySttHandler(BaseHTTPRequestHandler):
        server_version = "HandyVoice/1"

        def log_message(self, fmt: str, *args) -> None:
            # Keep request logs terse; never log transcripts or audio.
            print(f"[handy-voice] {self.address_string()} {fmt % args}")

        def do_GET(self) -> None:
            if self.path not in {"/health", "/healthz"}:
                _json(self, 404, {"error": "not found"})
                return
            status = engine.status()
            _json(
                self,
                200 if status.get("dependency_available", True) else 503,
                {"ok": bool(status.get("dependency_available", True)), **status},
            )

        def do_POST(self) -> None:
            if self.path != "/v1/audio/transcriptions":
                _json(self, 404, {"error": "not found"})
                return

            content_type = self.headers.get("content-type", "")
            if "multipart/form-data" not in content_type.lower():
                _json(self, 415, {"error": "multipart/form-data required"})
                return

            raw_len = self.headers.get("content-length", "")
            try:
                length = int(raw_len)
            except ValueError:
                _json(self, 411, {"error": "content-length required"})
                return
            # Allow multipart framing overhead while preserving Collie's 8 MiB audio ceiling.
            if length < 1 or length > MAX_AUDIO_BYTES + 1024 * 1024:
                _json(self, 413, {"error": "request too large"})
                return

            body = self.rfile.read(length)
            if len(body) != length:
                _json(self, 400, {"error": "incomplete request"})
                return

            env = {
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(length),
            }
            try:
                form = cgi.FieldStorage(
                    fp=io.BytesIO(body),
                    headers=self.headers,
                    environ=env,
                    keep_blank_values=True,
                )
                if "file" not in form:
                    _json(self, 400, {"error": "missing file"})
                    return
                item = form["file"]
                if isinstance(item, list):
                    item = item[0]
                audio = item.file.read()
                filename = item.filename or "recording.webm"
                language = form.getfirst("language") or None
            except Exception:
                _json(self, 400, {"error": "invalid multipart body"})
                return

            if not audio:
                _json(self, 400, {"error": "empty audio"})
                return
            if len(audio) > MAX_AUDIO_BYTES:
                _json(self, 413, {"error": "audio too large"})
                return

            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    prefix="handy-stt-", suffix=_extension(filename), delete=False
                ) as tmp:
                    tmp.write(audio)
                    tmp_path = tmp.name
                text = engine.transcribe(tmp_path, language)
                _json(self, 200, {"text": text})
            except Exception as exc:
                print(f"[handy-voice] transcription failure: {type(exc).__name__}: {exc}")
                _json(self, 500, {"error": "local transcription failed"})
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

    return HandySttHandler


def create_server(host: str, port: int, engine=None) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("Handy Voice must bind to loopback only")
    engine = engine or HandyWhisperEngine()
    return ThreadingHTTPServer((host, port), make_handler(engine))


def main() -> int:
    parser = argparse.ArgumentParser(description="Handy local STT server for Collie")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8792)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    engine = HandyWhisperEngine(args.model)
    server = create_server(args.host, args.port, engine)
    print(
        f"[handy-voice] listening on http://{args.host}:{args.port}/v1 "
        f"(faster-whisper model={args.model}, loopback only)"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
