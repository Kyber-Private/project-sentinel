# Keyless Local AI - Compact Extraction Revision

This is an **additional option**, not a replacement for the working OpenRouter version. No secrets or model weights are bundled in the source ZIP. Your original installation and cloud API settings are preserved.

## Windows quick start

1. Install [Python 3.13](https://www.python.org/downloads/), [Node.js LTS](https://nodejs.org/) and [Ollama](https://ollama.com/download/windows) once. Start the Ollama app.
2. Double-click **Start Sentinel Local AI.bat** in the project root. It installs dependencies if necessary, fetches `qwen3:8b` and opens two server windows.
3. Open http://localhost:3000. Load Nova Industries and run the analysis. For connection test, run `curl -X POST http://localhost:8000/api/health/openai-test` in Command Prompt.
4. If you have 8GB or less available RAM, use the smaller model first: open Command Prompt in the project root and run `set SENTINEL_OLLAMA_MODEL=qwen3:4b` followed by `"Start Sentinel Local AI.bat"`. It uses ~2.5GB for weights but is less reliable.

**Model download:** `qwen3:8b` approximately **5.2 GB** (model only); additional RAM is needed for context and the app. Inference may be slow without a GPU. If Ollama fails, check its logs and available memory.

## Manual start or other operating systems

1. Install Ollama and pull the model: `ollama pull qwen3:8b`.
2. Start backend with environment variable `SENTINEL_AI_PROVIDER=ollama` and optional `SENTINEL_OLLAMA_MODEL=qwen3:8b` (these variables can be placed in `backend/.env`). Set `SENTINEL_AGENT_CHAR_BUDGET=18000` and `OPENAI_TIMEOUT_SECONDS=300` for local hardware.
3. Start `python -m uvicorn main:app --port 8000` from backend with its virtualenv activated.
4. Start `npm run dev` from frontend and open http://localhost:3000.

The agent client calls **127.0.0.1:11434** using a schema-constrained Ollama API; no OpenAI or OpenRouter key is sent. Local Qwen3 uses **the same four role prompts**, but is **not equivalent in capability** to GPT-6 Luna. The Python forecasts remain unchanged. All agent outputs still receive Pydantic schema checks. Live inference results will depend on machine capacity and model compliance.

## Hackathon judges

- This is a **keyless**, not a **zero-install** version. Judges must install Ollama, download model weights, and run the application locally. GitHub itself cannot serve a working AI application by showing the code.
- For zero-install judging, use a hosted backend with securely managed model inference or a demonstration recording; do not publish a private OpenRouter API key.
- Use fictional financial data. This prototype has not been independently validated for real financial decisions, and frontend dependencies require security upgrades before public hosting.

## Verification performed

- Local no-key model routing and schema-validation paths covered by mocked tests.
- Existing deterministic finance/document tests checked.
- **Live Ollama/Qwen3 inference has not been tested on a GPU in this environment.** Do not claim measured parity with the cloud model or production readiness.

## Data Analyst reliability revision

Qwen3 8B previously produced malformed long JSON when extracting facts. This version asks for a **maximum of two observations from one source passage at a time** using a small schema. Long text blocks are split into overlapping windows while preserving source references. Values and quotes are verified against the original document before they are used. If a model request still fails, the Data Analyst step is clearly marked failed; the deterministic forecast engine can continue, but no AI extraction success is falsely reported.

The source-level change passed 65 focused offline tests and the Nova financial engine produced both project forecasts. **Full live Ollama success is not verified here.** Run `VERIFY_REAL_OLLAMA.bat` to check it against your model.
