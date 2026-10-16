# Creates the school's self-signed code-signing certificate once and stores it as
# the two GitHub secrets used by sign-installer.ps1. Run by the owner on their PC:
#   powershell -NoProfile -ExecutionPolicy Bypass -File installer\new-signing-certificate.ps1
# Requires the GitHub CLI (gh) logged in with access to the repository.
#
# ASCII only on purpose: Windows PowerShell 5 reads BOM-less .ps1 files as ANSI.
#
# - ca=false: the certificate only signs code; it cannot issue other certificates.
# - The private key leaves this PC only inside the encrypted GitHub secret; the
#   temporary .pfx is deleted at the end. Do not install this certificate as a
#   trusted root on other computers.
# - Self-signed: identifies the publisher, but does NOT remove the SmartScreen
#   warning. That needs a certificate from a recognized authority.
param(
    [string]$Name = 'Escola Ieda Alves de Oliveira - Coletor de Frequencia',
    [string]$Repository = 'mcpmieda/coletor-frequencia-smecel'
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'GitHub CLI (gh) not found' }
$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=$Name" -FriendlyName "$Name - assinatura de codigo" `
    -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -KeyExportPolicy Exportable -NotAfter (Get-Date).AddYears(10) `
    -CertStoreLocation Cert:\CurrentUser\My -TextExtension @('2.5.29.19={critical}{text}ca=false')
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$password = [Convert]::ToBase64String($bytes)
$secure = ConvertTo-SecureString -String $password -AsPlainText -Force
$pfx = Join-Path ([System.IO.Path]::GetTempPath()) ("coletor-signing-" + [guid]::NewGuid() + '.pfx')
try {
    Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $secure | Out-Null
    [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($pfx)) | gh secret set WINDOWS_SIGNING_PFX_BASE64 --repo $Repository
    $password | gh secret set WINDOWS_SIGNING_PFX_PASSWORD --repo $Repository
} finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
    Remove-Item "Cert:\CurrentUser\My\$($cert.Thumbprint)" -ErrorAction SilentlyContinue
}
Write-Host "Code-signing certificate stored as GitHub secrets. Thumbprint: $($cert.Thumbprint)"
