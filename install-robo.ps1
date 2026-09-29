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

# Windows PowerShell 5.1 turns anything a native program writes to stderr into
# a terminating error while $ErrorActionPreference is 'Stop' and the stream is
# redirected (e.g. a pip warning going to the extras log), which aborted the
# whole install. Run such calls with 'Continue'; callers check $LASTEXITCODE.
function Invoke-NativeRelaxed {
    param([scriptblock]$Script)
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Script } finally { $ErrorActionPreference = $prevEAP }
}

# The classic console window pauses a program while text is being selected,
# and a single click starts a selection ("Select" in the title bar) - the
# install then looks frozen until Esc is pressed. Turn QuickEdit off while
# installing and put the original console mode back at the end.
$script:QuickEditRestore = $null
function Disable-QuickEdit {
    try {
        if (-not ('RoboInstall.ConsoleMode' -as [type])) {
            Add-Type -Namespace RoboInstall -Name ConsoleMode -ErrorAction Stop -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)] public static extern IntPtr GetStdHandle(int nStdHandle);
[DllImport("kernel32.dll", SetLastError = true)] public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);
[DllImport("kernel32.dll", SetLastError = true)] public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
'@
        }
        $handle = [RoboInstall.ConsoleMode]::GetStdHandle(-10)
        [uint32]$mode = 0
        if (-not [RoboInstall.ConsoleMode]::GetConsoleMode($handle, [ref]$mode)) { return }
        $quickEdit = [uint32]0x40
        $extendedFlags = [uint32]0x80
        if (($mode -band $quickEdit) -eq 0) { return }
        $newMode = [uint32](($mode -bor $extendedFlags) -bxor $quickEdit)
        if ([RoboInstall.ConsoleMode]::SetConsoleMode($handle, $newMode)) {
            $script:QuickEditRestore = @($handle, $mode)
        }
    } catch { }
}
function Restore-QuickEdit {
    if (-not $script:QuickEditRestore) { return }
    try {
        [RoboInstall.ConsoleMode]::SetConsoleMode($script:QuickEditRestore[0], [uint32]$script:QuickEditRestore[1]) | Out-Null
    } catch { }
    $script:QuickEditRestore = $null
}

# Add a folder to the user PATH without flattening it: [Environment]'s
# Get/SetEnvironmentVariable would expand %USERPROFILE%-style entries and save
# them as plain text. Keeps the registry value's type, then lets Windows know
# the environment changed (the dummy variable round-trip broadcasts it) so
# new windows pick the new PATH up.
function Add-UserPathEntry {
    param([string]$Dir)
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
    if (-not $key) { return $false }
    try {
        $raw = [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
        if ($raw) { $kind = $key.GetValueKind('Path') }
        $parts = @($raw -split ';' | Where-Object { $_ })
        foreach ($part in $parts) {
            if ([Environment]::ExpandEnvironmentVariables($part).TrimEnd('\') -ieq $Dir.TrimEnd('\')) { return $false }
        }
        $key.SetValue('Path', ((@($parts) + $Dir) -join ';'), $kind)
    } finally {
        $key.Close()
    }
    [Environment]::SetEnvironmentVariable('ROBO_INSTALL_PATH_REFRESH', '1', 'User')
    [Environment]::SetEnvironmentVariable('ROBO_INSTALL_PATH_REFRESH', $null, 'User')
    return $true
}

Disable-QuickEdit
try {

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
        Invoke-NativeRelaxed { & $exe @prefix -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)" 2>$null }
        if ($LASTEXITCODE -eq 0) {
            $script:PythonPrefix = @($candidate)
            break
        }
    } catch {
        continue
    }
}

if (-not $script:PythonPrefix) {
    throw (@(
        'Robo requires Python 3.11, 3.12, or 3.13 (3.14 is not supported yet), and none was found.',
        'Install Python 3.13, open a NEW PowerShell window, and run this installer again:',
        '  winget install -e --id Python.Python.3.13',
        '  (or download it from https://www.python.org/downloads/windows/ and tick "Add python.exe to PATH")',
        'Python installed somewhere else? Point the installer at it:  .\install-robo.ps1 -Python C:\path\to\python.exe'
    ) -join [Environment]::NewLine)
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
Invoke-NativeRelaxed { & $venvPython -m pip --version *> $null }
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Existing Python environment has no pip; bootstrapping it...'
    Invoke-NativeRelaxed { & $venvPython -m ensurepip --upgrade *> $null }
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
    Invoke-NativeRelaxed { & $venvPython -m pip install --editable "$Root[$extra]" *>> $extrasLog }
    if ($LASTEXITCODE -eq 0) { $extrasOk += $extra; continue }
    if ($extra -eq 'wake') {
        Invoke-NativeRelaxed { & $venvPython -m pip install 'openwakeword==0.6.0' 'onnxruntime==1.27.0' 'sounddevice==0.5.5' *>> $extrasLog }
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
    if (Add-UserPathEntry -Dir $BinDir) {
        Write-Host "Added $BinDir to your user PATH. Open a new terminal after installation."
    }

    # Record the data folder for the user, so every Robo process agrees on it:
    # the desktop app and anything started without the robo.cmd launcher
    # otherwise default to %LOCALAPPDATA%\robo. Only when nothing is set yet
    # and no %LOCALAPPDATA%\robo data exists - never re-point an existing setup.
    $userRoboHome = [Environment]::GetEnvironmentVariable('ROBO_HOME', 'User')
    $localAppDataHome = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'robo' } else { $null }
    if (-not $userRoboHome) {
        if ($localAppDataHome -and (Test-Path -LiteralPath $localAppDataHome) -and ($localAppDataHome -ne $RoboHome)) {
            Write-Warning ("Robo data also exists in $localAppDataHome. The robo command uses $RoboHome; " +
                "the desktop app may use the other folder. To use one folder everywhere, set ROBO_HOME for your user.")
        } else {
            [Environment]::SetEnvironmentVariable('ROBO_HOME', $RoboHome, 'User')
        }
    } elseif ($userRoboHome.TrimEnd('\') -ne $RoboHome.TrimEnd('\')) {
        Write-Warning ("Your user ROBO_HOME is $userRoboHome, but this install uses $RoboHome. " +
            "The robo command uses $RoboHome; the desktop app uses $userRoboHome.")
    }
}

& $roboExe --robo-version
Write-Host ''
Write-Host 'Robo installed. Open a new terminal and run:'
Write-Host '  robo'
} finally {
    Restore-QuickEdit
}
