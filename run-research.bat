@echo off
REM run-research.bat — Called by Windows Task Scheduler to research AI grants
REM Uses DuckDuckGo search + MiniMax M2.5 (via LiteLLM) for extraction
REM Commits and pushes to trigger Vercel auto-deploy
REM Note: Python script handles its own logging to research.log

cd /d C:\flur_workspace
C:\Users\choranode\AppData\Local\Microsoft\WindowsApps\python.exe ai-grants\research-grants.py
