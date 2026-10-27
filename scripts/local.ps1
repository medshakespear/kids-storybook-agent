param([ValidateSet('Start', 'Stop', 'Logs')][string]$Action = 'Start')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Install Docker Desktop first: https://docs.docker.com/desktop/setup/install/windows-install/ . Open it, enable Linux containers, then run Start Local.cmd again.'
    }
    & docker info --format '{{.OSType}}' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Open Docker Desktop and wait until its engine is running, then try again.' }
    $composeArgs = @('compose', '--env-file', '.env.local', '-f', 'compose.local.yaml')
    if ($Action -ne 'Start' -and -not (Test-Path '.env.local')) {
        Write-Host 'No local installation settings exist yet. Run Start Local.cmd first.'
        exit 0
    }
    if (-not (Test-Path '.env.local')) {
        Copy-Item '.env.local.example' '.env.local'
        Write-Host 'Paste your Gemini key(s), Cloudflare token(s), and Cloudflare account ID into the file opening now. Save it, then close Notepad. Keep credentials on your computer.'
        Start-Process notepad.exe -ArgumentList '.env.local'
        Read-Host 'Save the file and close Notepad, then press Enter here' | Out-Null
    }
    if ($Action -eq 'Stop') {
        & docker @composeArgs stop
        if ($LASTEXITCODE -ne 0) { throw 'Could not stop the local service.' }
        Write-Host 'Stopped. Your PDFs and state remain in local-data.'
        exit 0
    }
    if ($Action -eq 'Logs') {
        & docker @composeArgs logs --tail 150 -f web
        exit $LASTEXITCODE
    }
    $settings = @{}
    foreach ($line in Get-Content '.env.local') {
        if ($line -match '^\s*([A-Z][A-Z0-9_]*)=(.*)$') { $settings[$Matches[1]] = $Matches[2].Trim() }
    }
    $hasGemini = @($settings.Keys | Where-Object { $_ -match '^GEMINI_API_KEY(_[1-4])?$' -and $settings[$_] }).Count -gt 0
    $hasCloudflare = @($settings.Keys | Where-Object { $_ -match '^CLOUDFLARE_API_TOKEN(_[1-4])?$' -and $settings[$_] }).Count -gt 0
    if (-not $hasGemini -or -not $hasCloudflare) {
        throw 'Open .env.local in Notepad and fill at least GEMINI_API_KEY_1, CLOUDFLARE_API_TOKEN_1, and CLOUDFLARE_ACCOUNT_ID. Save and run Start Local.cmd again. Use raw values without quotes.'
    }
    $port = if ($settings.ContainsKey('LOCAL_PORT')) { $settings['LOCAL_PORT'] } else { '8080' }
    if ($port -notmatch '^\d+$' -or [int]$port -lt 1024 -or [int]$port -gt 65535) { throw 'LOCAL_PORT must be 1024-65535.' }
    foreach ($slot in 1..4) {
        $token = $settings["CLOUDFLARE_API_TOKEN_$slot"]
        if ($slot -eq 1 -and -not $token) { $token = $settings['CLOUDFLARE_API_TOKEN'] }
        if ($token) {
            $account = $settings["CLOUDFLARE_ACCOUNT_ID_$slot"]
            if (-not $account) { $account = $settings['CLOUDFLARE_ACCOUNT_ID'] }
            if ($account -notmatch '^[a-fA-F0-9]{32}$') { throw "Fill a 32-character CLOUDFLARE_ACCOUNT_ID for token slot $slot in .env.local." }
        }
    }
    New-Item -ItemType Directory -Force 'local-data\output' | Out-Null
    Write-Host 'Starting the local workbook agent. The first build downloads PDF-rendering dependencies and can take several minutes.'
    & docker @composeArgs up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'Docker build/start failed. Read the error above; use a current Docker Desktop with Compose 2.30 or newer.' }
    & docker @composeArgs exec -T web python -c 'from core.providers import validate_providers; validate_providers()'
    if ($LASTEXITCODE -ne 0) { throw 'Provider settings are incomplete. Correct .env.local and run Start Local.cmd again.' }
    Write-Host 'Provider settings look valid; no AI requests made.'
    $url = "http://localhost:$port"
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $health = Invoke-RestMethod "$url/health" -TimeoutSec 2
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw 'The web interface did not become ready. Double-click View Logs.cmd to inspect startup errors.' }
    Start-Process $url
    Write-Host "Ready: $url . PDFs: $(Get-Location)\local-data\output . Use Stop Local.cmd when finished."
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
