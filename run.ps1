# Start the Tamil speech recognition service.
#   .\run.ps1              start on http://127.0.0.1:8000
#   .\run.ps1 -Port 9000   start on another port
#   .\run.ps1 -Reload      auto-reload on code changes (development)
param(
    [int]$Port = 8000,
    [string]$BindHost = "127.0.0.1",
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "No virtual environment found. Run: py -3.11 -m venv .venv"
}

$argv = @("-m", "uvicorn", "src.api:app", "--host", $BindHost, "--port", $Port)
if ($Reload) { $argv += "--reload" }

# The portal needs PostgreSQL. When docker-compose.yml's container exists but is
# stopped (e.g. after a reboot), bring it back; a custom DATABASE_URL is left alone.
if ((Get-Command docker -ErrorAction SilentlyContinue) -and (Test-Path (Join-Path $root "docker-compose.yml"))) {
    $state = (& docker inspect -f "{{.State.Running}}" tamiltutor-pg 2>$null)
    if ($state -eq "false") {
        Write-Host "Starting the PostgreSQL container (docker compose up -d db)..." -ForegroundColor DarkGray
        & docker compose -f (Join-Path $root "docker-compose.yml") up -d db | Out-Null
    }
}

Write-Host "Tamil Speech Recognition -> http://$BindHost`:$Port" -ForegroundColor Cyan
Write-Host "The first run downloads the model (several GB); it will take a while." -ForegroundColor DarkGray

Push-Location $root
try { & $python @argv } finally { Pop-Location }
