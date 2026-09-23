[CmdletBinding()]
param(
    [string]$RoboHome = $(if ($env:ROBO_HOME) { $env:ROBO_HOME } else { Join-Path $HOME '.robo' }),
    [string]$Python = '',
    [string]$Node = '',
    [string]$BinDir = '',
    [switch]$SkipNode,
    [switch]$NoPathUpdate
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$env:ROBO_HOME = $RoboHome

function Invoke-Python {
    param([string[]]$Arguments)
    if ($script:PythonPrefix.Count -gt 1) {
        & $script:PythonPrefix[0] $script:PythonPrefix[1] @Arguments
    } else {
        & $script:PythonPrefix[0] @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE"
    }
}

$candidates = @()
if ($Python) {
    $candidates += ,@($Python)
} else {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates += ,@('py', '-3.13')
        $candidates += ,@('py', '-3.12')
        $candidates += ,@('py', '-3.11')
    }
    foreach ($name in @('python3.13', 'python3.12', 'python3.11', 'python')) {
        if (Get-Command $name -ErrorAction SilentlyContinue) {
            $candidates += ,@($name)
        }
    }
}

$script:PythonPrefix = $null
foreach ($candidate in $candidates) {
    try {
        $exe = $candidate[0]
        $prefix = @()
        if ($candidate.Count -gt 1) { $prefix = @($candidate[1]) }
        & $exe @prefix -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $script:PythonPrefix = @($candidate)
            break
        }
    } catch {
        continue
    }
}

if (-not $script:PythonPrefix) {
    throw 'Robo requires Python 3.11, 3.12, or 3.13.'
}

if ($Node) {
    if (-not (Test-Path -LiteralPath $Node -PathType Leaf)) {
        throw "The supplied Node.js executable does not exist: $Node"
    }
    $Node = (Resolve-Path -LiteralPath $Node).Path
    $nodeVersion = & $Node --version
    if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v(\d+)\.') {
        throw "Could not run the supplied Node.js executable: $Node"
    }
    if ([int]$Matches[1] -lt 22) {
        throw "Robo requires Node.js 22 or newer; found $nodeVersion"
    }
    $env:Path = "$(Split-Path -Parent $Node);$env:Path"
}

New-Item -ItemType Directory -Force -Path $RoboHome | Out-Null

$sourceEnv = Join-Path $Root '.env'
$targetEnv = Join-Path $RoboHome '.env'
if ((Test-Path -LiteralPath $sourceEnv) -and -not (Test-Path -LiteralPath $targetEnv)) {
    Copy-Item -LiteralPath $sourceEnv -Destination $targetEnv
    Write-Host "Copied existing .env to $targetEnv"
}

$venv = Join-Path $Root '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'Creating Robo Python environment...'
    Invoke-Python -Arguments @('-m', 'venv', $venv)
}

# A .venv created by uv (developers running the test suite) ships without
# pip. Bootstrap it with ensurepip; if that interpreter cannot, rebuild the
# environment with the Python selected above instead of failing.
& $venvPython -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Existing Python environment has no pip; bootstrapping it...'
    & $venvPython -m ensurepip --upgrade *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Recreating the Robo Python environment...'
        Remove-Item -LiteralPath $venv -Recurse -Force
        Invoke-Python -Arguments @('-m', 'venv', $venv)
    }
}

& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw 'Failed to update the Python installer.' }
& $venvPython -m pip install --editable $Root
if ($LASTEXITCODE -ne 0) { throw 'Failed to install Robo.' }

# The hands-free stack ("Hey Roh Boh", local transcription, spoken replies) is
# three optional extras, installed one at a time so a missing wheel for one
# cannot take the others down. pip output goes to a log; a summary is printed.
$extrasLog = Join-Path $RoboHome 'logs\install-extras.log'
New-Item -ItemType Directory -Force -Path (Split-Path $extrasLog) | Out-Null
Set-Content -Path $extrasLog -Value ''
$extrasOk = @(); $extrasFailed = @()
foreach ($extra in @('voice', 'wake', 'edge-tts')) {
    Write-Host "Installing the $extra extra..."
    & $venvPython -m pip install --editable "$Root[$extra]" *>> $extrasLog
    if ($LASTEXITCODE -eq 0) { $extrasOk += $extra; continue }
    if ($extra -eq 'wake') {
        & $venvPython -m pip install 'openwakeword==0.6.0' 'onnxruntime==1.27.0' 'sounddevice==0.5.5' *>> $extrasLog
        if ($LASTEXITCODE -eq 0) { $extrasOk += 'wake(no sherpa-onnx)'; continue }
    }
    $extrasFailed += $extra
}
if ($extrasOk.Count -gt 0) { Write-Host ("Hands-free voice installed: " + ($extrasOk -join ' ')) }
if ($extrasFailed.Count -gt 0) {
    Write-Warning ("Not installed on this platform: " + ($extrasFailed -join ' ') + ". Details: $extrasLog  Check: robo doctor")
}

if (-not $SkipNode) {
    # Run the dependency helper in a child PowerShell process. The helper
    # intentionally exits when --ensure completes, so dot-running it would
    # end this installer before the Robo launcher is created.
    $powerShellHost = (Get-Process -Id $PID).Path
    & $powerShellHost -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'scripts\install.ps1') `
        -Ensure node `
        -RoboHome $RoboHome `
        -InstallDir $Root `
        -NonInteractive `
        -SkipSetup
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install the Node.js runtime.' }
}

if (-not $BinDir) {
    $BinDir = Join-Path $RoboHome 'bin'
}
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$roboExe = Join-Path $venv 'Scripts\robo.exe'
$wrapper = Join-Path $BinDir 'robo.cmd'
$wrapperBody = @"
@echo off
set "ROBO_HOME=$RoboHome"
"$roboExe" %*
"@
Set-Content -LiteralPath $wrapper -Value $wrapperBody -Encoding ascii

if (-not $NoPathUpdate) {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $pathParts = @($userPath -split ';' | Where-Object { $_ })
    if ($pathParts -notcontains $BinDir) {
        $nextPath = (@($pathParts) + $BinDir) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $nextPath, 'User')
        Write-Host "Added $BinDir to your user PATH. Open a new terminal after installation."
    }
}

& $roboExe --robo-version
Write-Host ''
Write-Host 'Robo installed. Open a new terminal and run:'
Write-Host '  robo'
