@echo off
cd /d "%~dp0"
echo Starting faster-whisper-server on http://127.0.0.1:8000/v1 ...
docker compose -f docker-compose.faster-whisper.yml up -d
echo.
echo If this is the first run, Docker will download the image and the model cache will be stored in data\huggingface-cache.
echo Configure diary_web .env with:
echo SPEECH_TO_TEXT_PROVIDER=openai
echo OPENAI_API_KEY=local-key-can-be-any-non-empty-value
echo OPENAI_BASE_URL=http://127.0.0.1:8000/v1
echo OPENAI_TRANSCRIBE_MODEL=Systran/faster-whisper-small
pause
