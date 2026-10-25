$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$cli = Join-Path $projectRoot '.railway-local/railway.exe'
if (-not (Test-Path -LiteralPath $cli)) { $cli = Join-Path $projectRoot '.railway-local/cli/node_modules/@railway/cli/bin/railway.exe' }
if (-not (Test-Path -LiteralPath $cli)) { throw 'Prepara la CLI con scripts/Deploy-Railway.ps1 o instala @railway/cli en .railway-local/cli.' }
$project = '344c5cac-566f-4f32-aaa8-9c444fd99a02'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$destination = Join-Path $projectRoot ".railway-local/backups/$timestamp"
New-Item -ItemType Directory -Path $destination -Force | Out-Null
& $cli service files --project $project --environment production --service Postgres upload scripts/railway-dump.sh /tmp/zeros-backup.sh --overwrite
if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar la copia de PostgreSQL.' }
& $cli ssh --project $project --environment production --service Postgres -- sh /tmp/zeros-backup.sh
if ($LASTEXITCODE -ne 0) { throw 'pg_dump no pudo completar la copia.' }
& $cli service files --project $project --environment production --service Postgres download /tmp/zeros-backup.dump (Join-Path $destination 'postgres.dump')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo descargar el dump.' }
& $cli service files --project $project --environment production --service Postgres download /tmp/zeros-backup-list.txt (Join-Path $destination 'postgres-list.txt')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo descargar el listado del dump.' }
& $cli service files --project $project --environment production --service poker download /data/table_layouts (Join-Path $destination 'table_layouts')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo descargar la calibracion.' }
# Profiles may be absent in deployments created before profile imports existed.
$ErrorActionPreference = 'Continue'
$profileListing = & $cli service files --project $project --environment production --service poker list /data/card_profiles 2>&1
$profileResult = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($profileResult -eq 0) {
    & $cli service files --project $project --environment production --service poker download /data/card_profiles (Join-Path $destination 'card_profiles')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron descargar los perfiles.' }
}
Get-ChildItem -LiteralPath $destination -File -Recurse | ForEach-Object { Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256 } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $destination 'checksums.json') -Encoding utf8
& $cli ssh --project $project --environment production --service Postgres -- rm -f /tmp/zeros-backup.dump /tmp/zeros-backup-list.txt /tmp/zeros-backup.sh
if ($LASTEXITCODE -ne 0) { Write-Warning 'La copia esta descargada; revisa los temporales de copia en /tmp del servicio.' }
Write-Host "Copia privada guardada en $destination"
Write-Host 'El dump ha sido validado con pg_restore --list. La restauracion se ensaya en una base aislada, nunca sobre produccion.'
