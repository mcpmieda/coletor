# Builds "Instalar Coletor.exe" from InstalarColetor.cs with the .NET Framework compiler that ships with
# Windows (no download). The CI builds, signs and publishes it with every Release (.github/workflows/checks.yml).
# Locally, from the repository root: powershell -File scripts\bootstrap\build.ps1 -Out <file>
param([Parameter(Mandatory = $true)][string]$Out)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $csc /nologo /codepage:65001 /optimize+ /target:winexe "/out:$Out" `
    "/win32icon:$(Join-Path $root 'app\assets\fox-icons\fox-idle.ico')" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Web.Extensions.dll `
    (Join-Path $PSScriptRoot 'InstalarColetor.cs')
if ($LASTEXITCODE -ne 0) { throw 'Falha ao compilar o Instalar Coletor.exe' }
