# Buduje arkusz stylów Tailwinda.
#
#   .\scripts\build_css.ps1          jednorazowy build (zminifikowany)
#   .\scripts\build_css.ps1 -Watch   tryb obserwowania zmian podczas pracy
#
# Używa standalone CLI z katalogu tools\ — bez Node'a i bez npm.

param([switch]$Watch)

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$cli = Join-Path $root "tools\tailwindcss.exe"

if (-not (Test-Path $cli)) {
    Write-Host "Brak $cli" -ForegroundColor Red
    Write-Host "Pobierz standalone CLI (40 MB):" -ForegroundColor Yellow
    Write-Host "  https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-windows-x64.exe"
    Write-Host "i zapisz jako tools\tailwindcss.exe"
    exit 1
}

$arguments = @(
    "-c", (Join-Path $root "tailwind.config.js"),
    "-i", (Join-Path $root "app\static\css\input.css"),
    "-o", (Join-Path $root "app\static\css\tailwind.css")
)

if ($Watch) { $arguments += "--watch" } else { $arguments += "--minify" }

& $cli @arguments
