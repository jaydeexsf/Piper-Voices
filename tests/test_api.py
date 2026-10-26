"""API and input-validation tests for the Piper Voices HTTP service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _write_silent_wav(text: str, wav_file) -> None:
    wav_file.setframerate(22050)
    wav_file.setsampwidth(2)
    wav_file.setnchannels(1)
    wav_file.writeframes(b"\x00\x00" * 256)


@pytest.fixture
def client():
    fake_voice = MagicMock()
    fake_voice.synthesize_wav.side_effect = _write_silent_wav

    with patch("app.main.load_voice", return_value=fake_voice):
        from app.main import app

        with TestClient(app) as test_client:
            yield test_client, fake_voice


def test_health_ok(client) -> None:
    test_client, _voice = client
    response = test_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert "voice" in body


def test_tts_returns_wav(client) -> None:
    test_client, fake_voice = client
    response = test_client.post(
        "/tts", json={"text": "Hello, this is Piper speaking."}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content[:4] == b"RIFF"
    assert b"WAVE" in response.content[:16]
    fake_voice.synthesize_wav.assert_called_once()
    args, _kwargs = fake_voice.synthesize_wav.call_args
    assert args[0] == "Hello, this is Piper speaking."


def test_tts_rejects_empty_text(client) -> None:
    test_client, fake_voice = client
    response = test_client.post("/tts", json={"text": "   "})
    assert response.status_code == 422
    assert "error" in response.json()
    fake_voice.synthesize_wav.assert_not_called()


def test_tts_rejects_missing_text(client) -> None:
    test_client, _voice = client
    response = test_client.post("/tts", json={})
    assert response.status_code == 422
    assert "error" in response.json()


def test_tts_rejects_excessively_long_text(client) -> None:
    test_client, fake_voice = client
    from app.main import MAX_TEXT_LENGTH

    response = test_client.post("/tts", json={"text": "a" * (MAX_TEXT_LENGTH + 1)})
    assert response.status_code == 422
    assert "error" in response.json()
    fake_voice.synthesize_wav.assert_not_called()


def test_tts_does_not_leak_internal_errors(client) -> None:
    test_client, fake_voice = client
    fake_voice.synthesize_wav.side_effect = RuntimeError("secret onnx path /tmp/hidden")
    response = test_client.post("/tts", json={"text": "Hello"})
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "Failed to synthesize speech."
    assert "secret" not in response.text
    assert "/tmp/hidden" not in response.text
