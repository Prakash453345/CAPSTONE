@echo off
title ITMS 3D Web App Launcher
echo Starting ITMS 3D City Website...

cd /d "C:\Users\vivek\.gemini\antigravity\scratch\CAPSTONE\itms\web-app"
start "" "http://localhost:5173"
call "C:\Program Files\nodejs\npm.cmd" run dev

pause
