# Builds instalador\Instalar Coletor.exe from InstalarColetor.cs with the .NET Framework compiler that
# ships with Windows (no download). Run from the repository root: powershell -File scripts\bootstrap\build.ps1
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$out = Join-Path $root 'instalador\Instalar Coletor.exe'
& $csc /nologo /codepage:65001 /optimize+ /target:winexe "/out:$out" `
    "/win32icon:$(Join-Path $root 'app\assets\fox-icons\fox-idle.ico')" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Web.Extensions.dll `
    (Join-Path $PSScriptRoot 'InstalarColetor.cs')
if ($LASTEXITCODE -ne 0) { throw 'Falha ao compilar o Instalar Coletor.exe' }
(Get-FileHash $out -Algorithm SHA256).Hash.ToLower() + '  Instalar Coletor.exe'
