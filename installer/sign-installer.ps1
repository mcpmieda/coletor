# Signs a binary with the code-signing certificate of the build: the school's on main (a secret of
# the GitHub environment "assinatura"), a throwaway one in any other CI build.
# Usage (CI): sign-installer.ps1 -Path dist\windows-installer\Setup.exe
#   env WINDOWS_SIGNING_BUNDLE_BASE64  base64 JSON with pfx and password (new-signing-certificate.ps1)
# Without it (a build on a developer's computer) the binary stays unsigned; the CI then refuses it
# (scripts/check_windows_signature.py).
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
if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "File to sign not found: $Path" }
if (-not $env:WINDOWS_SIGNING_BUNDLE_BASE64) {
    Write-Warning 'Code-signing certificate not configured: this binary is NOT signed.'
    exit 0
}
$json = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:WINDOWS_SIGNING_BUNDLE_BASE64))
$bundle = ConvertFrom-Json -InputObject $json
if (-not $bundle.pfx -or -not $bundle.password) { throw 'Incomplete signing bundle' }
$bytes = [Convert]::FromBase64String($bundle.pfx)
$flags = [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet
$cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($bytes, $bundle.password, $flags)
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
    } catch { Write-Warning "Not signed with $server ($($_.Exception.Message))" }
}
if (-not $signed) { throw 'Binary signature with timestamp was not applied' }
$check = Get-AuthenticodeSignature $Path
if ($check.SignerCertificate.Thumbprint -ne $cert.Thumbprint -or -not $check.TimeStamperCertificate -or
    $check.Status -notin @('Valid', 'UnknownError', 'NotTrusted')) { throw 'Binary signature mismatch' }
Write-Host "Binary signing status: $($check.Status); publisher: $($cert.Subject)"
