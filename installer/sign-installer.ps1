# Signs the Setup with the school's code-signing certificate kept as GitHub secrets.
# Usage (CI): sign-installer.ps1 -Path dist\windows-installer\Setup.exe
#   env WINDOWS_SIGNING_BUNDLE_BASE64  base64 JSON with pfx and password
#   Legacy: WINDOWS_SIGNING_PFX_BASE64 and WINDOWS_SIGNING_PFX_PASSWORD
#
# ASCII only on purpose: Windows PowerShell 5 reads BOM-less .ps1 files as ANSI.
#
# What the signature does: names the school as publisher in the file properties
# and proves the file was not changed after signing.
# What it does NOT do (self-signed certificate): remove the SmartScreen warning or
# pass Smart App Control. Only a certificate from a recognized authority does that.
# The program itself runs on the official python(w).exe signed by the Python
# Software Foundation; that executable is never re-signed.
param([Parameter(Mandatory = $true)][string]$Path)
$ErrorActionPreference = 'Stop'
if ($env:WINDOWS_SIGNING_BUNDLE_BASE64) {
    $json = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:WINDOWS_SIGNING_BUNDLE_BASE64))
    $bundle = ConvertFrom-Json -InputObject $json
    if (-not $bundle.pfx -or -not $bundle.password) { throw 'Incomplete signing bundle' }
    $pfxBase64, $pfxPassword = $bundle.pfx, $bundle.password
} elseif ($env:WINDOWS_SIGNING_PFX_BASE64 -or $env:WINDOWS_SIGNING_PFX_PASSWORD) {
    if (-not $env:WINDOWS_SIGNING_PFX_BASE64 -or -not $env:WINDOWS_SIGNING_PFX_PASSWORD) {
        throw 'Incomplete legacy signing certificate configuration'
    }
    $pfxBase64, $pfxPassword = $env:WINDOWS_SIGNING_PFX_BASE64, $env:WINDOWS_SIGNING_PFX_PASSWORD
} else {
    Write-Warning 'Code-signing certificate not configured: this binary is NOT signed.'
    exit 0
}
$bytes = [Convert]::FromBase64String($pfxBase64)
$flags = [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet
$cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($bytes, $pfxPassword, $flags)
if (-not $cert.HasPrivateKey) { throw 'Signing certificate has no private key' }
$codeSigning = $cert.EnhancedKeyUsageList | Where-Object { $_.ObjectId -eq '1.3.6.1.5.5.7.3.3' }
if (-not $codeSigning) { throw 'Certificate is not a code-signing certificate' }
# Timestamp keeps the signature valid after the certificate expires; servers go down at times.
$servers = 'http://timestamp.digicert.com', 'http://timestamp.sectigo.com', 'http://time.certum.pl'
$signed = $false
foreach ($server in $servers) {
    try {
        $result = Set-AuthenticodeSignature -FilePath $Path -Certificate $cert -HashAlgorithm SHA256 -TimestampServer $server
        if ($result.SignerCertificate -and $result.TimeStamperCertificate) { $signed = $true; break }
    } catch { Write-Warning "Timestamp server unavailable: $server" }
}
if (-not $signed) { throw 'Binary signature with timestamp was not applied' }
$check = Get-AuthenticodeSignature $Path
if ($check.SignerCertificate.Thumbprint -ne $cert.Thumbprint -or -not $check.TimeStamperCertificate -or
    $check.Status -notin @('Valid', 'UnknownError', 'NotTrusted')) { throw 'Binary signature mismatch' }
Write-Host "Binary signing status: $($check.Status); publisher: $($cert.Subject)"
