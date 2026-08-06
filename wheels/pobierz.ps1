# Pobiera wszystkie paczki potrzebne do NOXSO CRM (75 plikow, ok. 62 MB).
#
# Uruchom w sieci BEZ blokady PyPI (hotspot z telefonu, dom, inny komputer):
#     powershell -ExecutionPolicy Bypass -File wheels\pobierz.ps1
#
# Pliki ladują do tego samego katalogu. Potem, juz w dowolnej sieci:
#     .venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r requirements-dev.txt

$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$lista = Join-Path $dir "lista-url.txt"

if (-not (Test-Path $lista)) {
    Write-Host "Brak pliku lista-url.txt obok skryptu." -ForegroundColor Red
    exit 1
}

# TLS 1.2 - starsze konfiguracje Windows probuja domyslnie TLS 1.0 i dostaja odmowe
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$urls = Get-Content $lista | Where-Object { $_.Trim() -ne "" }
$i = 0
$pobrane = 0
$pominiete = 0
$bledy = @()

foreach ($url in $urls) {
    $i++
    $nazwa = Split-Path $url -Leaf
    $cel = Join-Path $dir $nazwa

    if ((Test-Path $cel) -and (Get-Item $cel).Length -gt 0) {
        $pominiete++
        Write-Host ("[{0,2}/{1}] {2} - juz jest" -f $i, $urls.Count, $nazwa) -ForegroundColor DarkGray
        continue
    }

    Write-Host ("[{0,2}/{1}] {2}" -f $i, $urls.Count, $nazwa) -NoNewline
    $ok = $false
    for ($proba = 1; $proba -le 3 -and -not $ok; $proba++) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $cel -UseBasicParsing -ErrorAction Stop
            if ((Get-Item $cel).Length -eq 0) { throw "pobrano 0 bajtow" }
            $ok = $true
        }
        catch {
            if (Test-Path $cel) { Remove-Item $cel -Force -ErrorAction SilentlyContinue }
            if ($proba -eq 3) { $bledy += "$nazwa - $($_.Exception.Message)" }
            else { Start-Sleep -Seconds 2 }
        }
    }
    if ($ok) {
        $pobrane++
        Write-Host ("  OK ({0:N0} KB)" -f ((Get-Item $cel).Length / 1KB)) -ForegroundColor Green
    }
    else {
        Write-Host "  BLAD" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Pobrano: $pobrane, pominieto (juz byly): $pominiete, bledow: $($bledy.Count)"

if ($bledy.Count -gt 0) {
    Write-Host ""
    Write-Host "Nieudane - uruchom skrypt ponownie, pobierze tylko brakujace:" -ForegroundColor Yellow
    $bledy | ForEach-Object { Write-Host "  $_" }
    exit 1
}

Write-Host ""
Write-Host "Gotowe. Teraz w katalogu projektu:" -ForegroundColor Green
Write-Host "  .venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r requirements-dev.txt"
