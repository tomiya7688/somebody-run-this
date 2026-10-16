$ErrorActionPreference = "Stop"

$BaseDir = $PSScriptRoot
$ServerExe = Join-Path $BaseDir "fx-channel-server.exe"
$ConfigFile = Join-Path $BaseDir "config\operator.yaml"
$ContentDir = Join-Path $BaseDir "content"
$WebUserDir = Join-Path $BaseDir "web-user"

if (-not (Test-Path $ServerExe)) {
    throw "fx-channel-server.exe not found: $ServerExe"
}

if (-not (Test-Path $ConfigFile)) {
    throw "config\operator.yaml not found. Copy operator.example.yaml first."
}

if ([string]::IsNullOrWhiteSpace($env:FX_CHANNEL_OPERATOR_TOKEN)) {
    throw "FX_CHANNEL_OPERATOR_TOKEN is not set."
}

& $ServerExe --operator $ConfigFile --content $ContentDir --web-user $WebUserDir
exit $LASTEXITCODE
