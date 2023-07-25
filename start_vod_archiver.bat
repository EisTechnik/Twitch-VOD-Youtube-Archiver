:: Cannot run powershell directly
:: CMD has reliability issues with high concurrency downloads in yt-dlp
@echo off
start powershell -file "./start_vod_archiver.ps1"

TIMEOUT /T 5
