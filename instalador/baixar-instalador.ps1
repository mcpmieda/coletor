# Downloads the newest Coletor installer from GitHub Releases into this folder,
# checks its SHA-256 and opens it. Only github.com is contacted; nothing is sent.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repository = 'https://github.com/mcpmieda/coletor/releases'
$folder = $PSScriptRoot
$manifestFile = Join-Path $folder 'atualizacao.json.part'
try {
    Invoke-WebRequest "$repository/latest/download/atualizacao.json" -OutFile $manifestFile -UseBasicParsing
    $manifest = Get-Content $manifestFile -Raw | ConvertFrom-Json
} finally {
    Remove-Item -LiteralPath $manifestFile -ErrorAction SilentlyContinue
}
$version = [string]$manifest.versao
if ($version -notmatch '^\d+\.\d+\.\d+$' -or $manifest.arquivo -ne "COLETOR-v$version.exe" -or
    [string]$manifest.sha256 -notmatch '^[0-9a-f]{64}$') {
    throw 'A versao publicada nao tem um formato valido.'
}
$target = Join-Path $folder "COLETOR v$version.exe"
function Test-Setup($path) {
    (Test-Path -LiteralPath $path) -and
        ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower() -eq $manifest.sha256)
}
if (-not (Test-Setup $target)) {
    $partial = "$target.part"
    Invoke-WebRequest "$repository/download/v$version/$($manifest.arquivo)" -OutFile $partial -UseBasicParsing
    if (-not (Test-Setup $partial)) {
        Remove-Item -LiteralPath $partial -ErrorAction SilentlyContinue
        throw 'O arquivo baixado nao confere com o publicado. Tente de novo.'
    }
    Move-Item -LiteralPath $partial -Destination $target -Force
}
Get-ChildItem -LiteralPath $folder -Filter 'COLETOR v*.exe' | Where-Object { $_.FullName -ne $target } | Remove-Item
Write-Host "Instalador pronto: $target"
Start-Process -FilePath $target
