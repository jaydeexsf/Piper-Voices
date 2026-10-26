# Piper Voices API

HTTP API around [Piper](https://github.com/OHF-Voice/piper1-gpl) that turns text into WAV audio. Synthesis runs entirely on the server with a local ONNX voice. There is no paid TTS provider.

This repository is a clone of the Piper engine plus a small FastAPI service in `app/` intended for Railway, with a Vercel/Next.js frontend calling `POST /tts`.

**This deployment is not guaranteed to stay within Railway’s free allowance.** The `en_US-lessac-medium` voice is a compact starting point, but ONNX Runtime still needs a meaningful amount of RAM (plan for at least 1 GB).

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness check. Returns JSON with `status`, `voice`, and `model_loaded`. |
| `POST` | `/tts` | JSON body `{"text":"..."}`. Response is `audio/wav`. |

Limits:

- Empty or whitespace-only `text` is rejected (`422`).
- Default maximum length is 2000 characters (`MAX_TEXT_LENGTH`).
- Concurrent synthesis is serialized (`MAX_CONCURRENT_TTS`, default `1`) so two requests cannot run ONNX at the same time and exhaust memory.

## Local setup (Windows)

Use the existing virtual environment. Do not replace it.

```powershell
.\.venv\Scripts\python.exe -m pip install fastapi==0.118.0 "uvicorn[standard]==0.37.0" httpx==0.28.1 pytest==8.4.2
```

`piper-tts` is already installed in this environment. Voice files `en_US-lessac-medium.onnx` and `en_US-lessac-medium.onnx.json` should sit in the project root (or in `PIPER_MODEL_DIR`).

Copy `.env.example` to `.env` if you want to override settings. The process reads standard environment variables; it does not require python-dotenv.

Start the API:

```powershell
$env:PIPER_VOICE = "en_US-lessac-medium"
$env:PIPER_MODEL_DIR = "."
$env:ALLOWED_ORIGINS = "http://localhost:3000"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health check:

```powershell
curl http://127.0.0.1:8000/health
```

Synthesize:

```powershell
curl.exe -X POST http://127.0.0.1:8000/tts -H "Content-Type: application/json" -d "{\"text\":\"Hello, this is Piper speaking.\"}" --output api-test.wav
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_api.py
```

These tests mock Piper so they do not download models. They cover health, WAV content type, empty text, missing text, overly long text, and hidden internal errors.

## Voice model storage

| Environment | Location | Survives restart? |
| --- | --- | --- |
| Local | `PIPER_MODEL_DIR` (default: project root) | Yes, files on disk |
| Docker / Railway | `/app/models` inside the image | Yes, the model is copied into the image at **build** time |

The Docker build runs `python -m piper.download_voices en_US-lessac-medium` once. Requests never download a voice.

A Railway volume is **not required** for this architecture. Add one only if you later download extra voices at runtime and want them to outlive a new image deploy.

`DOWNLOAD_MISSING_VOICE=false` in the image so a missing file fails at startup instead of hitting Hugging Face on boot.

## Docker

```powershell
docker build -t piper-voices-api .
docker run --rm -p 8000:8000 -e ALLOWED_ORIGINS=http://localhost:3000 piper-voices-api
```

The image installs `piper-tts` from PyPI rather than compiling this repository, which keeps the build smaller than a from-source Piper image.

## Railway deployment

1. Push this project to GitHub (`https://github.com/jaydeexsf/Piper-Voices.git`).
2. In [Railway](https://railway.app), create a new project → **Deploy from GitHub repo** → select `Piper-Voices`.
3. Railway should detect `Dockerfile` and `railway.json`.
4. Set variables (no secrets are required for the default voice):

   | Variable | Example |
   | --- | --- |
   | `ALLOWED_ORIGINS` | `https://your-app.vercel.app` |
   | `PIPER_VOICE` | `en_US-lessac-medium` (already the image default) |
   | `MAX_TEXT_LENGTH` | `2000` |
   | `MAX_CONCURRENT_TTS` | `1` |

   Railway injects `PORT`. The container binds `0.0.0.0:$PORT`.
5. Give the service enough memory (1 GB is a reasonable starting point). Do not assume the free tier will be enough.
6. Use the generated `*.up.railway.app` URL. `GET /health` should return `"status": "ok"` after the model has loaded (the health check waits up to 30 seconds).

CORS is **not** `*` by default. If `ALLOWED_ORIGINS` is empty, browsers on Vercel will be blocked; server-side `fetch` from Next.js Route Handlers still works.

## Calling the public API from Next.js (Vercel)

Set `PIPER_API_URL` on Vercel to the Railway origin, for example `https://piper-voices-production.up.railway.app` (no trailing slash).

Prefer a server-side route so the Railway URL stays off the browser if you want it private:

```ts
// app/api/speak/route.ts
export async function POST(request: Request) {
  const { text } = await request.json();
  const piperUrl = process.env.PIPER_API_URL;
  if (!piperUrl) {
    return Response.json({ error: "PIPER_API_URL is not set" }, { status: 500 });
  }

  const response = await fetch(`${piperUrl}/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });

  if (!response.ok) {
    return Response.json({ error: "TTS request failed" }, { status: response.status });
  }

  return new Response(response.body, {
    headers: { "Content-Type": "audio/wav" },
  });
}
```

Browser playback:

```ts
const audioResponse = await fetch("/api/speak", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ text: "Hello, this is Piper speaking." }),
});
const blob = await audioResponse.blob();
const url = URL.createObjectURL(blob);
new Audio(url).play();
```

If you call Railway directly from the browser, set `ALLOWED_ORIGINS` to your Vercel origin (`https://your-app.vercel.app`). Do not set it to `*` in production.

## Configuration

See `.env.example` for every variable. None of them are secrets for the default setup.

## Upstream Piper engine

The rest of this repository is the Piper TTS project (GPL-3.0-or-later) from [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl).

- [CLI](docs/CLI.md)
- [Python API](docs/API_PYTHON.md)
- [Built-in Flask HTTP server](docs/API_HTTP.md)
- [Voices](docs/VOICES.md)
- [Building](docs/BUILDING.md)
- [Training](docs/TRAINING.md)
