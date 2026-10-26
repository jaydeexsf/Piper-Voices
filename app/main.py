"""FastAPI service that synthesizes WAV audio with a local Piper voice."""

from __future__ import annotations

import io
import logging
import os
import threading
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from piper import PiperVoice
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("piper_api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

MAX_TEXT_LENGTH = int(os.getenv("MAX_TEXT_LENGTH", "2000"))
MAX_CONCURRENT_TTS = max(1, int(os.getenv("MAX_CONCURRENT_TTS", "1")))
PIPER_VOICE = os.getenv("PIPER_VOICE", "en_US-lessac-medium")
PIPER_MODEL_DIR = Path(os.getenv("PIPER_MODEL_DIR", ".")).expanduser()
PIPER_MODEL_PATH = os.getenv("PIPER_MODEL_PATH")
DOWNLOAD_MISSING_VOICE = os.getenv("DOWNLOAD_MISSING_VOICE", "true").lower() in {
    "1",
    "true",
    "yes",
}


def _allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _model_path() -> Path:
    if PIPER_MODEL_PATH:
        return Path(PIPER_MODEL_PATH).expanduser()
    return PIPER_MODEL_DIR / f"{PIPER_VOICE}.onnx"


def load_voice() -> PiperVoice:
    """Load the configured ONNX voice, downloading once at startup if needed."""
    model_path = _model_path()
    config_path = Path(f"{model_path}.json")
    if not model_path.is_file() or not config_path.is_file():
        if not DOWNLOAD_MISSING_VOICE:
            raise FileNotFoundError(
                f"Voice model not found for '{PIPER_VOICE}'. "
                "Set PIPER_MODEL_DIR / PIPER_MODEL_PATH or enable DOWNLOAD_MISSING_VOICE."
            )
        from piper.download_voices import download_voice

        PIPER_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading voice %s into %s", PIPER_VOICE, PIPER_MODEL_DIR)
        download_voice(PIPER_VOICE, PIPER_MODEL_DIR)
        model_path = PIPER_MODEL_DIR / f"{PIPER_VOICE}.onnx"

    if not model_path.is_file():
        raise FileNotFoundError(f"Voice model file is missing: {model_path.name}")

    logger.info("Loading Piper voice %s", PIPER_VOICE)
    return PiperVoice.load(model_path)


_voice: Optional[PiperVoice] = None
_tts_gate = threading.BoundedSemaphore(MAX_CONCURRENT_TTS)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _voice
    _voice = load_voice()
    try:
        yield
    finally:
        _voice = None


app = FastAPI(
    title="Piper Voices API",
    description="Local text-to-speech using Piper.",
    lifespan=lifespan,
)

_origins = _allowed_origins()
if _origins:
    allow_all = _origins == ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else _origins,
        allow_credentials=not allow_all,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)

    @field_validator("text")
    @classmethod
    def text_must_contain_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Text must not be empty.")
        if len(cleaned) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"Text exceeds the maximum length of {MAX_TEXT_LENGTH} characters."
            )
        return cleaned


def _error_payload(message: str) -> dict[str, str]:
    return {"error": message}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=_error_payload("Invalid request. Check that 'text' is present and valid."),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(status_code=exc.status_code, content=_error_payload(detail))


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
    logger.exception("Unhandled server error")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_payload("Internal server error."),
    )


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "voice": PIPER_VOICE,
        "model_loaded": _voice is not None,
    }


def _synthesize_wav_bytes(text: str) -> bytes:
    if _voice is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice model is not loaded.",
        )

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        _voice.synthesize_wav(text, wav_file)
    return buffer.getvalue()


@app.post("/tts")
def text_to_speech(payload: TTSRequest) -> Response:
    acquired = _tts_gate.acquire(timeout=30)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Server is busy synthesizing audio. Try again shortly.",
        )

    try:
        audio = _synthesize_wav_bytes(payload.text)
        return Response(content=audio, media_type="audio/wav")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Speech synthesis failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to synthesize speech.",
        )
    finally:
        _tts_gate.release()
