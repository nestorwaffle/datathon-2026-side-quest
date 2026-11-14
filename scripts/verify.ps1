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
& ./.venv/Scripts/python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& ./.venv/Scripts/python.exe predict.py --input data/demo.jsonl --output .devflight/predictions.csv --backend demo
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& ./.venv/Scripts/python.exe eval.py --input data/demo.jsonl --predictions .devflight/predictions.csv --recipe demo --tokens 0 --recipe-config data/recipe.json
exit $LASTEXITCODE
