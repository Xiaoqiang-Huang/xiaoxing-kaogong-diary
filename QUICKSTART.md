# Quick Start

## Windows: one-click startup

1. Install Python 3.11 or later.
2. Double-click `setup_and_run.bat`.
3. Open `http://127.0.0.1:5000`.
4. Go to `/register` and create your first account.

The script will:

- create `.venv`
- install dependencies from `requirements.txt`
- copy `.env.example` to `.env`
- generate a local `SECRET_KEY`
- start the Flask app

## Manual startup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python start.py
```

Open:

```text
http://127.0.0.1:5000
```

## Configure AI

The app can run without an AI key, but AI replies will use a fallback mode.

To enable the built-in AI, edit `.env`:

```env
ANTHROPIC_API_KEY=your-key
ANTHROPIC_BASE_URL=your-compatible-endpoint
```

After login, an admin can also change the built-in AI API from `/settings`.

## Configure speech-to-text

For local free speech-to-text, start faster-whisper-server:

```powershell
docker compose -f docker-compose.faster-whisper.yml up -d
```

Then edit `.env`:

```env
SPEECH_TO_TEXT_PROVIDER=openai
OPENAI_API_KEY=local-key-can-be-any-non-empty-value
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_TRANSCRIBE_MODEL=Systran/faster-whisper-small
```

## Run tests

```powershell
python -m unittest discover tests -v
```

