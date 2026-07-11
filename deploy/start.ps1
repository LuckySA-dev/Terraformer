[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$SecretScript = Join-Path $PSScriptRoot "init-secrets.py"
$ComposeFile = Join-Path $PSScriptRoot "compose.yml"
$EnvironmentFile = Join-Path $RepositoryRoot ".env"

Push-Location $RepositoryRoot
try {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 $SecretScript
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python $SecretScript
    }
    else {
        throw "Python 3 is required to initialize local file secrets."
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Secret initialization failed. Existing secrets were not rotated."
    }

    $ComposeArguments = @("compose")
    if (Test-Path -LiteralPath $EnvironmentFile) {
        $ComposeArguments += @("--env-file", $EnvironmentFile)
    }
    $ComposeArguments += @("-f", $ComposeFile, "up", "--build", "--detach", "--wait")

    & docker @ComposeArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

