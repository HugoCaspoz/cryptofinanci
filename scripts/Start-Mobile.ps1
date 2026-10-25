param(
    [string]$BindAddress,
    [switch]$ConfigureFirewall
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

if (-not $BindAddress) {
    $interfaces = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address }
    $selected = $interfaces | Sort-Object { $_.NetIPv4Interface.InterfaceMetric } | Select-Object -First 1
    if (-not $selected) { throw 'No hay una interfaz LAN con puerta de enlace. Conecta el ordenador al Wi-Fi o usa -BindAddress.' }
    $BindAddress = ($selected.IPv4Address | Select-Object -First 1).IPAddress
}
$parsedAddress = $null
if (-not [System.Net.IPAddress]::TryParse($BindAddress, [ref]$parsedAddress) -or $parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'BindAddress debe ser una IPv4 de este ordenador.'
}
$localInterface = Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -eq $BindAddress | Select-Object -First 1
if (-not $localInterface -or $BindAddress -eq '0.0.0.0' -or $BindAddress.StartsWith('127.')) { throw 'Elige la IP de la interfaz local conectada al movil.' }
if (-not ($BindAddress.StartsWith('10.') -or $BindAddress.StartsWith('192.168.') -or ($parsedAddress.GetAddressBytes()[0] -eq 172 -and $parsedAddress.GetAddressBytes()[1] -ge 16 -and $parsedAddress.GetAddressBytes()[1] -le 31))) {
    throw 'Este acceso esta preparado para una red privada, no para una IP publica.'
}

$privateDirectory = Join-Path $projectRoot '.mobile'
New-Item -ItemType Directory -Path $privateDirectory -Force | Out-Null
$passwordPath = Join-Path $privateDirectory 'password.txt'
$environmentPath = Join-Path $privateDirectory 'config.env'
if (Test-Path -LiteralPath $passwordPath) {
    $mobilePassword = (Get-Content -LiteralPath $passwordPath -Raw).Trim()
} else {
    $randomBytes = New-Object byte[] 15
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($randomBytes) } finally { $generator.Dispose() }
    $mobilePassword = [Convert]::ToBase64String($randomBytes).Replace('+','-').Replace('/','_')
    [IO.File]::WriteAllText($passwordPath, $mobilePassword)
}
$mobileHash = & docker run --rm caddy:2-alpine caddy hash-password --plaintext $mobilePassword
if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar Caddy. Comprueba Docker Desktop.' }
$mobileHash = ($mobileHash | Select-Object -Last 1).Trim()
if (-not $mobileHash.StartsWith('$2')) { throw 'No se genero un hash bcrypt valido.' }
[IO.File]::WriteAllText($environmentPath, "MOBILE_BIND_IP='$BindAddress'`nMOBILE_AUTH_HASH='$mobileHash'`n")
$composeArguments = @()
if (Test-Path -LiteralPath (Join-Path $projectRoot '.env')) { $composeArguments += @('--env-file', '.env') }
$composeArguments += @('--env-file', '.mobile/config.env', '-f', 'compose.yaml', '-f', 'compose.mobile.yaml', '--profile', 'mobile')
& docker compose @composeArguments up --build -d --wait
if ($LASTEXITCODE -ne 0) { throw 'No se pudo iniciar el acceso movil.' }
$containerId = & docker compose @composeArguments ps -q mobile
& docker cp "${containerId}:/data/caddy/pki/authorities/local/root.crt" (Join-Path $privateDirectory 'zeros-root.crt')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo exportar el certificado local.' }

$firewallMessage = 'Si el movil no conecta, ejecuta este script como administrador con -ConfigureFirewall.'
if ($ConfigureFirewall) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Warning 'Los servicios estan listos. Para crear la regla de firewall usa PowerShell como administrador.'
    } else {
        Get-NetFirewallRule -Name 'Zeros-Mobile-LAN' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        New-NetFirewallRule -Name 'Zeros-Mobile-LAN' -DisplayName 'Zeros camera - local subnet only' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5443,5444 -LocalAddress $BindAddress -RemoteAddress LocalSubnet -InterfaceAlias $localInterface.InterfaceAlias -Profile Any | Out-Null
        $firewallMessage = 'Firewall configurado: solo subred local, interfaz seleccionada y puertos 5443/5444.'
    }
}
$accessText = @"
Zeros - acceso desde el movil

Misma red local que el ordenador.
1. Descarga e instala el certificado: http://${BindAddress}:5444/zeros-root.crt
   iPhone: Ajustes > Perfil descargado > Instalar; despues General > Informacion > Ajustes de confianza de certificados y activa esta autoridad local.
   Android: Ajustes > Seguridad > Cifrado y credenciales > Instalar certificado > Certificado de CA (el nombre varia segun el fabricante).
2. Abre https://${BindAddress}:5443/live
   Usuario: zeros
   Contrasena: $mobilePassword
3. Pulsa Usar camara y permite la camara. Movil fijo y horizontal; manten la pestana visible.

$firewallMessage
No publiques estos puertos en el router. El certificado solo es para esta instalacion.
Si cambia la IP Wi-Fi, vuelve a ejecutar el script.
"@
[IO.File]::WriteAllText((Join-Path $privateDirectory 'access.txt'), $accessText)
Write-Host "App: https://${BindAddress}:5443/live"
Write-Host 'Usuario, contrasena y pasos: .mobile/access.txt'
Write-Host $firewallMessage
