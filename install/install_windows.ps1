# ============================================================================
# Calcium Network Pipeline - one-click installer for Windows
#
# Started by double-clicking INSTALL_WINDOWS.bat. No administrator password is
# needed: everything goes into one folder (C:\CalciumPipeline, or
# %USERPROFILE%\CalciumPipeline if that is not allowed) plus %USERPROFILE%\Cascade
# and %USERPROFILE%\.cellpose. Nothing else on the PC is changed.
#
# What it does:
#   1. Puts a private copy of Python ("Miniforge") in <install>\conda - separate
#      from any Python you already have, so it cannot break it.
#   2. Builds the four environments the pipeline needs, at the exact versions the
#      reference numbers were produced with (suite2p, cascade, analysis, gui).
#   3. Downloads CASCADE with its two jGCaMP8 models, and the Cellpose model.
#   4. Copies the pipeline code to <install>\code.
#   5. Puts a "Calcium Pipeline" shortcut on the Desktop.
#   6. Runs a self-test on synthetic data and says PASSED or FAILED.
#
# Safe to run again: finished steps are skipped. Run it again after downloading a
# newer version of the pipeline to update the code (environments are kept).
#
# This file must stay plain ASCII: Windows PowerShell 5.1 misreads other characters.
# ============================================================================
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'     # the progress bar makes downloads 10x slower
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Src = Split-Path -Parent $PSScriptRoot      # the downloaded pipeline folder
$CascadeSha = '213fd1206653bbb9dbe68a5faa8c0dab91fc46ee'   # the CASCADE version we verified
$Models = @('GC8s_EXC_45Hz_smoothing50ms', 'GC8f_EXC_100Hz_smoothing10ms')
$CascadeDir = Join-Path $env:USERPROFILE 'Cascade'

function Step($msg) { Write-Host ''; Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  OK    $msg" -ForegroundColor Green }
function Note($msg) { Write-Host "  NOTE  $msg" -ForegroundColor Yellow }
function Die($msg) {
    Write-Host ''
    Write-Host "  STOPPED: $msg" -ForegroundColor Red
    if ($script:Log) { Write-Host "  The full log is in: $script:Log" }
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}

# ---------------------------------------------------------------- install folder
# A SHORT path matters on Windows: TensorFlow's files are nested very deep, and
# Windows refuses paths over 260 characters unless an administrator has turned on
# long paths. Conda also dislikes spaces and accented letters in its path.
function Test-Writable($dir) {
    try {
        New-Item -ItemType Directory -Force -Path $dir -ErrorAction Stop | Out-Null
        $probe = Join-Path $dir '.write_test'
        Set-Content -Path $probe -Value 'x' -ErrorAction Stop
        Remove-Item $probe -Force
        return $true
    } catch { return $false }
}
if ($env:CNP_BASE) {
    $Base = $env:CNP_BASE
} elseif (Test-Writable 'C:\CalciumPipeline') {
    $Base = 'C:\CalciumPipeline'
} else {
    $Base = Join-Path $env:USERPROFILE 'CalciumPipeline'
}
if (-not (Test-Writable $Base)) { Die "Cannot create the install folder $Base." }
$CondaHome = Join-Path $Base 'conda'
$Code = Join-Path $Base 'code'
$script:Log = Join-Path $Base 'install_log.txt'
Start-Transcript -Path $script:Log -Append | Out-Null

Write-Host "Calcium Network Pipeline installer - $(Get-Date)"
Write-Host "Installing into: $Base"

# ---------------------------------------------------------------- 1. checks
Step '1/7  Checking this PC'
if (-not [Environment]::Is64BitOperatingSystem) { Die 'This PC runs 32-bit Windows; the pipeline needs 64-bit Windows.' }
if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
    Die 'This PC has an ARM processor. The pipeline needs an Intel or AMD (x64) PC.'
}
Ok "Windows $([Environment]::OSVersion.Version), 64-bit"
if ($Base -match '[^\x21-\x7E]') {
    Die "The install folder path ($Base) contains a space or an accented letter. Ask IT to allow creating C:\CalciumPipeline, or set CNP_BASE to a simple path."
}
$drive = (Get-Item $Base).PSDrive
$freeGB = [math]::Floor($drive.Free / 1GB)
if ($freeGB -lt 15) { Die "Only $freeGB GB free on drive $($drive.Name):, the install needs about 15 GB." }
Ok "$freeGB GB free on drive $($drive.Name):"
# Any answer from the server - even an HTTP error page - proves the network path works;
# only "no response at all" means offline or blocked.
$online = $false
try {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://conda.anaconda.org/conda-forge/' -TimeoutSec 30 -ErrorAction Stop | Out-Null
    $online = $true
} catch {
    if ($_.Exception.Response) { $online = $true }
}
if (-not $online) {
    Die 'Cannot reach the internet (conda.anaconda.org). Check the network, or ask IT whether conda.anaconda.org, pypi.org, files.pythonhosted.org and github.com are blocked.'
}
Ok 'internet connection works'
$lp = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -ErrorAction SilentlyContinue).LongPathsEnabled
if ($lp -ne 1 -and $Base.Length -gt 20) {
    Note "Windows long paths are off and the install folder ($Base) is long. If installing TensorFlow fails with 'No such file or directory', ask IT to enable long paths or to allow C:\CalciumPipeline."
}
Note 'Antivirus software scans every file the installer writes. On some lab PCs that makes this take 1-3 hours. A step that seems stuck is usually still working - please leave the window open.'

# ---------------------------------------------------------------- 2. miniforge
Step '2/7  Private Python (Miniforge)'
$Conda = Join-Path $CondaHome 'Scripts\conda.exe'
if (Test-Path $Conda) {
    Ok 'already installed'
} else {
    $exe = Join-Path $Base 'Miniforge3-Windows-x86_64.exe'
    Write-Host '  downloading Miniforge (about 90 MB)...'
    try {
        Invoke-WebRequest -UseBasicParsing -OutFile $exe -ErrorAction Stop `
            -Uri 'https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Windows-x86_64.exe'
    } catch { Die "Download of Miniforge failed: $($_.Exception.Message)" }
    Write-Host '  installing Miniforge (a few minutes; no window will appear)...'
    # JustMe = this user only, so Windows never asks for an administrator password.
    # /D= must come last and must not be quoted.
    $mfArgs = "/InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /NoShortcuts=1 /NoRegistry=1 /S /D=$CondaHome"
    Start-Process -FilePath $exe -ArgumentList $mfArgs -Wait
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path $Conda)) { Die 'Miniforge did not install.' }
    Ok 'installed'
}

# ---------------------------------------------------------------- 3. envs
function EnvPy($name) { Join-Path $CondaHome "envs\$name\python.exe" }
function Build-Env($name, $pyver, $condaPkgs, $pipPkgs) {
    $prefix = Join-Path $CondaHome "envs\$name"
    $marker = Join-Path $prefix '.cnp_ok'
    if (Test-Path $marker) { Ok "${name}: already built"; return }
    Write-Host "  building $name ..."
    if (Test-Path $prefix) { Remove-Item -Recurse -Force $prefix }
    $cargs = @('create', '-y', '-q', '-p', $prefix, '-c', 'conda-forge', '--override-channels',
               "python=$pyver", 'pip') + $condaPkgs
    & $Conda @cargs | Out-Host
    if ($LASTEXITCODE -ne 0) { Die "Could not build the $name environment." }
    if ($pipPkgs.Count -gt 0) {
        $pargs = @('-m', 'pip', 'install', '-q', '--no-input') + $pipPkgs
        & (EnvPy $name) @pargs | Out-Host
        if ($LASTEXITCODE -ne 0) { Die "Could not install packages into the $name environment." }
    }
    Set-Content -Path $marker -Value 'ok'
    Ok "${name}: built"
}

Step '3/7  Environments (the longest step: 20 minutes to a few hours)'
# Version pins = the verified reference machine. Do not loosen them: Cellpose runs
# through torch, so a different torch/numpy can change which cells are detected,
# and TensorFlow 2.15 requires numpy < 2. pip installs the CPU build of torch.
Build-Env 'suite2p' '3.11' @() @('suite2p[gui]==1.0.0.1', 'cellpose==4.1.1', 'torch==2.11.0',
    'numpy==1.26.4', 'scipy==1.17.1', 'tifffile==2026.3.3')
Build-Env 'cascade' '3.10' @('numpy=1.26.4', 'h5py=3.16.0', 'ruamel.yaml', 'matplotlib-base') `
    @('tensorflow==2.15.1', 'scipy==1.15.3')
Build-Env 'analysis' '3.10' @('numpy=2.2.5', 'pandas=2.3.3', 'matplotlib=3.10.9', 'openpyxl=3.1.5',
    'jinja2=3.1.6', 'ruamel.yaml') @('scipy==1.15.3')
Build-Env 'gui' '3.11' @() @('streamlit==1.63.0', 'pandas==3.0.5', 'openpyxl==3.1.5', 'numpy==2.4.6',
    'scipy==1.17.1', 'tifffile==2026.3.3')

# ---------------------------------------------------------------- 4. CASCADE
Step '4/7  CASCADE and its models'
if (Test-Path (Join-Path $CascadeDir 'cascade2p')) {
    Ok "CASCADE already present at $CascadeDir"
} elseif ((Test-Path $CascadeDir) -and (Get-ChildItem $CascadeDir -Force | Select-Object -First 1)) {
    Die "$CascadeDir exists but is not CASCADE. Rename or move that folder, then run this again."
} else {
    Write-Host '  downloading CASCADE...'
    $zip = Join-Path $Base 'cascade.zip'
    $tmp = Join-Path $Base '_cascade_unzip'
    try {
        Invoke-WebRequest -UseBasicParsing -OutFile $zip -ErrorAction Stop `
            -Uri "https://github.com/HelmchenLabSoftware/Cascade/archive/$CascadeSha.zip"
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        Expand-Archive -Path $zip -DestinationPath $tmp -ErrorAction Stop
    } catch { Die "Download of CASCADE failed: $($_.Exception.Message)" }
    if (Test-Path $CascadeDir) { Remove-Item -Recurse -Force $CascadeDir }
    Move-Item (Join-Path $tmp "Cascade-$CascadeSha") $CascadeDir
    Remove-Item -Recurse -Force $tmp, $zip -ErrorAction SilentlyContinue
    Ok "CASCADE installed at $CascadeDir"
}
foreach ($m in $Models) {
    $mdir = Join-Path $CascadeDir "Pretrained_models\$m"
    if (Get-ChildItem -Path $mdir -Filter '*.h5' -ErrorAction SilentlyContinue) {
        Ok "model $m present"
        continue
    }
    Write-Host "  downloading model $m..."
    $py = "import os, sys, warnings; warnings.filterwarnings('ignore'); os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'; sys.path.insert(0, '.'); from cascade2p import cascade; cascade.download_model('$m', verbose=0)"
    Push-Location $CascadeDir
    & (EnvPy 'cascade') -c $py | Out-Host
    Pop-Location
    if (-not (Get-ChildItem -Path $mdir -Filter '*.h5' -ErrorAction SilentlyContinue)) {
        Die "Could not download the CASCADE model $m (the server drive.switch.ch may be blocked on this network - ask IT)."
    }
    Ok "model $m downloaded"
}

Step '5/7  Cellpose cell-detection model (about 1.2 GB, one time)'
& (EnvPy 'suite2p') -c 'from cellpose import models; models.CellposeModel(gpu=False)' | Out-Null
if ($LASTEXITCODE -eq 0) { Ok 'Cellpose model ready' }
else { Note 'Could not download the Cellpose model now; it will be downloaded on the first analysis.' }

# ---------------------------------------------------------------- 5. code + shortcut
Step '6/7  Pipeline code and Desktop shortcut'
if ((Resolve-Path $Src).Path -ne $Code) {
    robocopy $Src $Code /MIR /XD .git __pycache__ /XF settings.local.json /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Die "Could not copy the pipeline code to $Code." }
    Ok "code copied to $Code"
}

$launcher = Join-Path $Base 'Calcium Pipeline.bat'
$gui = EnvPy 'gui'
@"
@echo off
title Calcium Network Pipeline
REM Opens the Calcium Network Pipeline in your web browser.
REM Keep this window open while you work; closing it closes the program.
set "CNP_CONDA_BASE=$CondaHome"
set PYTHONUTF8=1
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)
echo Starting the Calcium Network Pipeline - your browser will open in a moment.
echo Keep this window open while you use it. Close it when you are done.
"$gui" -m streamlit run "$Code\gui\app.py" --server.address localhost --server.headless false --client.toolbarMode minimal
pause
"@ | Set-Content -Path $launcher -Encoding ASCII

try {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path $desktop 'Calcium Pipeline.lnk'))
    $lnk.TargetPath = $launcher
    $lnk.WorkingDirectory = $Base
    $lnk.Description = 'Calcium Network Pipeline'
    $lnk.Save()
    Ok 'shortcut placed on the Desktop: "Calcium Pipeline"'
} catch {
    Note "Could not make a Desktop shortcut. Start the program by double-clicking $launcher"
}

# ---------------------------------------------------------------- 6. self-test
Step '7/7  Self-test (about 3-10 minutes)'
$env:CNP_CONDA_BASE = $CondaHome
$env:PYTHONUTF8 = '1'
& (EnvPy 'analysis') (Join-Path $Code 'install\self_test.py') | Out-Host
if ($LASTEXITCODE -ne 0) {
    Die "The self-test FAILED (details above). Send the file $script:Log to the pipeline's maintainers."
}
Write-Host ''
Write-Host 'INSTALLATION COMPLETE - self-test PASSED.' -ForegroundColor Green
Write-Host 'To start: double-click "Calcium Pipeline" on your Desktop.'
try { Stop-Transcript | Out-Null } catch {}
exit 0
