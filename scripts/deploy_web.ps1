[CmdletBinding()]
param(
    [string]$SshTarget = "vps-root",
    [string]$RemoteDeployUser = "yoyopod-web-deploy",
    [switch]$NoInstall,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Native {
    param(
        [Parameter(Mandatory)]
        [string]$Command,
        [Parameter(ValueFromRemainingArguments)]
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE"
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$artifactRoot = Join-Path $repoRoot ".artifacts\web"
$installerSource = Join-Path $repoRoot "deploy\web\install-release.sh"

Push-Location $repoRoot
try {
    $dirty = & git status --porcelain
    if ($LASTEXITCODE -ne 0) {
        throw "git status failed"
    }
    if ($dirty) {
        throw "Refusing to deploy a dirty working tree. Commit or stash the intended changes first."
    }

    $commitSha = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $commitSha -notmatch "^[0-9a-f]{40}$") {
        throw "Could not resolve the current commit SHA"
    }

    $buildArgs = @("scripts/build_web.mjs")
    if ($NoInstall) {
        $buildArgs += "--no-install"
    }
    Invoke-Native node @buildArgs

    Copy-Item -LiteralPath (Join-Path $repoRoot "www\server\notify-collector.mjs") `
        -Destination (Join-Path $artifactRoot "notify-collector.mjs") -Force
    Set-Content -LiteralPath (Join-Path $artifactRoot "REVISION") `
        -Value $commitSha -Encoding ascii -NoNewline

    $timestamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $releaseId = "$timestamp-$($commitSha.Substring(0, 12))"
    $archiveName = "yoyopod-web-$releaseId.tar.gz"
    $archivePath = Join-Path $artifactRoot $archiveName
    $installerName = "install-release.sh"
    $stagedInstaller = Join-Path $artifactRoot $installerName

    Copy-Item -LiteralPath $installerSource -Destination $stagedInstaller -Force
    Invoke-Native tar "-czf" $archivePath "-C" $artifactRoot `
        "root" "docs" "notify-collector.mjs" "REVISION"

    if ($DryRun) {
        Write-Host "Dry run complete."
        Write-Host "Commit: $commitSha"
        Write-Host "Archive: $archivePath"
        return
    }

    $remoteDir = "/tmp/yoyopod-web-$releaseId"
    $remotePrepared = $false
    try {
        Invoke-Native ssh $SshTarget `
            "install -d -m 0755 '$remoteDir'"
        $remotePrepared = $true

        Push-Location $artifactRoot
        try {
            # Windows OpenSSH handles these relative paths reliably with legacy SCP.
            Invoke-Native scp "-O" $archiveName $installerName `
                "${SshTarget}:$remoteDir/"
        }
        finally {
            Pop-Location
        }

        $remoteCommand = @(
            "chown -R '$RemoteDeployUser`:$RemoteDeployUser' '$remoteDir'"
            "sudo -u '$RemoteDeployUser' bash '$remoteDir/$installerName' '$remoteDir/$archiveName' '$releaseId' '$commitSha'"
        ) -join " && "
        Invoke-Native ssh $SshTarget $remoteCommand
    }
    finally {
        if ($remotePrepared) {
            & ssh $SshTarget "rm -rf -- '$remoteDir'"
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Remote staging cleanup failed: $remoteDir"
            }
        }
    }

    Write-Host "Deployed $commitSha as $releaseId via $SshTarget"
}
finally {
    Pop-Location
}
