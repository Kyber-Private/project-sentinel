@echo off
setlocal
cd /d "%~dp0"
echo.
echo =============================================================
echo Sentinel REAL Qwen3 Verification (no mocks / no API keys)
echo =============================================================
echo.
echo Keep the NEW local Ollama Sentinel backend running on port 8000.
echo This creates a new Nova Industries analysis and calls all agents.
echo It may take several minutes depending on your GPU.
echo.
where python >nul 2>nul || (echo ERROR: Python not found. & pause & exit /b 1)
python "%~dp0Verify_Real_Ollama.py"
if errorlevel 1 (
 echo.
 echo FAILED. Open OLLAMA_LIVE_TEST_RESULT.txt and send it to ChatGPT.
) else (
 echo.
 echo PASSED. All 4 agents, financial forecasts, and PDF were checked.
)
pause
