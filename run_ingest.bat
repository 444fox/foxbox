@echo off
title Camera Ingest Setup

echo Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Download it from https://python.org
    pause
    exit /b 1
)

echo Installing dependencies...
pip install -r requirements.txt --quiet

echo Launching Camera Ingest...
python camera_ingest.py

pause
