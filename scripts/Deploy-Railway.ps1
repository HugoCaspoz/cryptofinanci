$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$cliPath = Join-Path $projectRoot '.railway-local/railway.exe'
if (-not (Test-Path -LiteralPath $cliPath)) {
    New-Item -ItemType Directory -Path .railway-local -Force | Out-Null
    & npm install --prefix .railway-local/cli @railway/cli
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo instalar la CLI de Railway.' }
    $cliPath = Join-Path $projectRoot '.railway-local/cli/node_modules/@railway/cli/bin/railway.exe'
}
# SDK checks the native CLI executable; the npm .cmd shim cannot be spawned
# by execFileSync on Windows. Point it at the verified native executable.
$env:_ = $cliPath
& $cliPath whoami
if ($LASTEXITCODE -ne 0) { throw 'Inicia sesion con npx @railway/cli login y vuelve a ejecutar.' }
& $cliPath link --project 344c5cac-566f-4f32-aaa8-9c444fd99a02 --environment production --service poker
if ($LASTEXITCODE -ne 0) { throw 'No se pudo enlazar zeros-poker-lab.' }
& $cliPath config apply --yes
if ($LASTEXITCODE -ne 0) { throw 'Revisa railway config plan antes de desplegar. No se aplicaron eliminaciones.' }
& $cliPath up --service poker
if ($LASTEXITCODE -ne 0) { throw 'Railway no ha confirmado un despliegue correcto.' }
