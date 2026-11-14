param([int]$Port = 8787)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (Test-Path .env) {
    Get-Content .env | Where-Object { $_ -match '^\s*([^#=]+)=(.*)$' } | ForEach-Object {
        $k = $matches[1].Trim()
        $v = $matches[2].Trim().Trim('"').Trim("'")
        if (-not [System.Environment]::GetEnvironmentVariable($k, 'Process')) {
            [System.Environment]::SetEnvironmentVariable($k, $v, 'Process')
        }
    }
}
$projectPython = Join-Path (Get-Location) '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'Primero crea .venv e instala el proyecto siguiendo README.md.'
}
& $projectPython -m devflight --home .devflight/telemetry collect --port $Port
