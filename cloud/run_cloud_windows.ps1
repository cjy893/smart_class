param(
    [switch]$Check,
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

if ($Config -eq "") {
    $Config = Join-Path $RepoRoot "cloud\config\cloud_config.yaml"
}

$env:CLOUD_CONFIG = $Config
$ArgsList = @("cloud/src/main.py", "--config", $Config)
if ($Check) {
    $ArgsList += "--check"
}

python @ArgsList
