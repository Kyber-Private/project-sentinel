@echo off
cd /d "%~dp0"
set "SENTINEL_AI_PROVIDER=ollama"
if not defined SENTINEL_OLLAMA_MODEL set "SENTINEL_OLLAMA_MODEL=qwen3:8b"
set "SENTINEL_AGENT_CHAR_BUDGET=18000"
set "OPENAI_TIMEOUT_SECONDS=300"
set "OPENAI_MAX_RETRIES=1"
echo Running local, no-key AI model %SENTINEL_OLLAMA_MODEL%
echo If port 8000 is occupied, close the OLD Sentinel backend first.
".venv\Scripts\python.exe" -m uvicorn main:app --port 8000
