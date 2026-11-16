@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PROJECT=%CD%"
if not defined SENTINEL_OLLAMA_MODEL set "SENTINEL_OLLAMA_MODEL=qwen3:8b"
echo.
echo ========================================================
echo   PROJECT SENTINEL - LOCAL AI (NO API KEY REQUIRED)
echo ========================================================
echo.
echo AI model: %SENTINEL_OLLAMA_MODEL%
echo Your original backend .env and OpenRouter key will NOT be changed.
echo.
where python >nul 2>nul || (echo ERROR: Python 3.11-3.13 required. & goto :failed)
where npm >nul 2>nul || (echo ERROR: Node.js and npm required. & goto :failed)
where ollama >nul 2>nul || (echo ERROR: Install Ollama from https://ollama.com/download/windows & goto :failed)
echo Checking Ollama...
ollama list >nul 2>nul || (echo ERROR: Start the Ollama application first. & goto :failed)
ollama show "%SENTINEL_OLLAMA_MODEL%" >nul 2>nul
if errorlevel 1 (
  echo Downloading open-source AI model - may require several gigabytes.
  ollama pull "%SENTINEL_OLLAMA_MODEL%" || goto :failed
)
if not exist "backend\.venv\Scripts\python.exe" (
  echo Creating Python environment...
  python -m venv "backend\.venv" || goto :failed
)
echo Installing/checking backend dependencies...
"backend\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt" || goto :failed
if not exist "frontend\node_modules" (
  echo Installing frontend dependencies...
  pushd frontend
  call npm install
  if errorlevel 1 (popd & goto :failed)
  popd
)
echo.
echo Opening backend and frontend...
start "Sentinel Backend (Local AI)" cmd /k ""%PROJECT%\backend\Run_Local_Backend.bat""
start "Sentinel Frontend" cmd /k ""%PROJECT%\frontend\Run_Local_Frontend.bat""
echo.
echo Open http://localhost:3000 in your browser.
echo Keep both new terminal windows open while using Sentinel.
echo To confirm the model works, run:
echo curl -X POST http://localhost:8000/api/health/openai-test
echo.
pause
exit /b 0
:failed
echo.
echo Setup stopped. Read LOCAL_AI_SETUP.md for details.
pause
exit /b 1
