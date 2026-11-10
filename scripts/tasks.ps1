# Windows task runner. Usage: ./scripts/tasks.ps1 test
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("install", "test", "lint", "format", "typecheck", "migrate", "up", "config")]
    [string]$Task
)

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

switch ($Task) {
    "install" {
        Push-Location apps/api; uv sync; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; Pop-Location
        Push-Location apps/web; npm install; exit $LASTEXITCODE
    }
    "test" { Set-Location apps/api; uv run pytest -q; exit $LASTEXITCODE }
    "lint" {
        Push-Location apps/api; uv run ruff check .; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; Pop-Location
        Set-Location apps/web; npm run lint; exit $LASTEXITCODE
    }
    "format" { Set-Location apps/api; uv run ruff format .; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; uv run ruff check --fix .; exit $LASTEXITCODE }
    "typecheck" {
        Push-Location apps/api; uv run mypy app; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; Pop-Location
        Set-Location apps/web; npm run typecheck; exit $LASTEXITCODE
    }
    "migrate" { Set-Location apps/api; uv run alembic upgrade head; exit $LASTEXITCODE }
    "up" { docker compose up -d postgres redis; exit $LASTEXITCODE }
    "config" { docker compose config --quiet; exit $LASTEXITCODE }
}
