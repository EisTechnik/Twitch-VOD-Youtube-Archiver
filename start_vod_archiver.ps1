# Since .ps1 files can't simply be executed (i.e. double clicking), use

#===RUN AS ADMIN===
if (!([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process PowerShell -Verb RunAs "-NoProfile -ExecutionPolicy Bypass -Command `"cd '$pwd'; & '$PSCommandPath';`"";
    exit;
}
#===END RUN-AS-ADMIN===

cd src
poetry run python main.py

echo "Waiting 5 seconds before closing..."
Start-Sleep -Seconds 5
[System.Threading.Thread]::Sleep(5000)
