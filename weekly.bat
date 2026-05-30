@echo off
REM weekly.bat - run by Windows Task Scheduler every Monday.
REM Full pipeline: research -> report -> git push (Vercel auto-deploys) -> notify (push/email/telegram).
setlocal
set PYTHONIOENCODING=utf-8
cd /d C:\flur_workspace\ai-grants
"C:\Users\choranode\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe" weekly.py >> weekly-run.log 2>&1
endlocal
