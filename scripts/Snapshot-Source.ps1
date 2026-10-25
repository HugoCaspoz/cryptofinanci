$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$archive = Join-Path $projectRoot '.railway-local/source-history.git'
if (-not (Test-Path -LiteralPath $archive)) {
    & git init --quiet --bare $archive
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el historial local de respaldo.' }
}
$gitArguments = @("--git-dir=$archive", "--work-tree=$projectRoot")
& git @gitArguments -c core.autocrlf=false add -A -- . ':(exclude).env*' ':(exclude).git/**'
if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar la instantanea.' }
$paths = & git @gitArguments ls-files
if ($paths | Where-Object { $_ -match '(^|/)(\.mobile|\.railway-local|node_modules|sample_data)/|(^|/)\.env($|\.)' }) {
    throw 'Se encontro una ruta privada en el respaldo; no se creara el commit.'
}
& git @gitArguments -c user.name='Poker Lab local backup' -c user.email='backup@localhost' -c commit.gpgsign=false commit --quiet -m 'Validated Poker Lab source snapshot'
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 1) { throw 'No se pudo guardar la instantanea.' }
Write-Host 'Instantanea guardada en .railway-local/source-history.git. El repositorio original y sus remotos no se han cambiado.'
