# Creates the school's self-signed code-signing certificate once and stores it as one atomic
# secret of the GitHub environment "assinatura", used by sign-installer.ps1. Run by the owner:
#   powershell -NoProfile -ExecutionPolicy Bypass -File installer\new-signing-certificate.ps1
# Requires the GitHub CLI (gh) logged in as an administrator of the repository.
#
# ASCII only on purpose: Windows PowerShell 5 reads BOM-less .ps1 files as ANSI.
#
# - The environment accepts only the main branch: a workflow pushed on any other branch cannot
#   read the secret, so only what was merged into main can sign.
# - The SHA-256 printed at the end is what installed Coletors and "Instalar Coletor.exe" accept
#   (SIGNERS in app/coletor/updater.py, Signers in scripts/bootstrap/InstalarColetor.cs). A new
#   certificate must be added there in a version signed by the previous one, or every computer
#   has to be reinstalled by hand.
# - ca=false: the certificate only signs code; it cannot issue other certificates.
# - The private key leaves this PC only inside the encrypted GitHub secret; the temporary .pfx is
#   deleted at the end. Do not install this certificate as a trusted root on other computers.
# - Self-signed: identifies the publisher, but does NOT remove the SmartScreen warning. That needs
#   a certificate from a recognized authority.
# - -Throwaway (the CI, outside main): nothing is stored; the bundle of a two-day certificate is
#   printed, so every build exercises the same signing and checks as a published one.
param(
    [string]$Name = 'Escola Ieda Alves de Oliveira - Coletor',
    # The repository of this checkout (gh reads its remote), unless another one is given.
    [string]$Repository = '',
    [string]$Environment = 'assinatura',
    [switch]$Throwaway
)
$ErrorActionPreference = 'Stop'
if (-not $Throwaway) {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'GitHub CLI (gh) not found' }
    if (-not $Repository) { $Repository = gh repo view --json nameWithOwner --jq .nameWithOwner }
    if ($LASTEXITCODE -ne 0 -or -not $Repository) { throw 'Repository not found. Run inside the checkout or pass -Repository owner/name.' }
}
$subject, $expires = "CN=$Name", (Get-Date).AddYears(10)
if ($Throwaway) { $subject, $expires = 'CN=Coletor - certificado de teste do CI (nao distribuir)', (Get-Date).AddDays(2) }
$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $subject -FriendlyName "$Name - assinatura de codigo" `
    -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -KeyExportPolicy Exportable -NotAfter $expires `
    -CertStoreLocation Cert:\CurrentUser\My -TextExtension @('2.5.29.19={critical}{text}ca=false')
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$password = [Convert]::ToBase64String($bytes)
$secure = ConvertTo-SecureString -String $password -AsPlainText -Force
$pfx = Join-Path ([System.IO.Path]::GetTempPath()) ("coletor-signing-" + [guid]::NewGuid() + '.pfx')
$published = $false
try {
    Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $secure | Out-Null
    # A single secret prevents PFX/password version skew on partial uploads.
    $bundle = @{ pfx = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($pfx)); password = $password } | ConvertTo-Json -Compress
    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($bundle))
    if ($Throwaway) {
        $published = $true
        Write-Output $encoded
    } else {
        # The environment and its single allowed branch first: the secret never exists outside it.
        '{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}' |
            gh api --method PUT "repos/$Repository/environments/$Environment" --input - | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'GitHub environment could not be created.' }
        $branches = @(gh api "repos/$Repository/environments/$Environment/deployment-branch-policies" --jq '.branch_policies[].name')
        if ($LASTEXITCODE -ne 0) { throw 'GitHub environment branches could not be read.' }
        if ("$branches" -ne 'main') {
            if ($branches) { throw "Environment $Environment accepts other branches ($branches). Remove them first." }
            gh api --method POST "repos/$Repository/environments/$Environment/deployment-branch-policies" -f name=main -f type=branch | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'GitHub environment could not be limited to main.' }
        }
        # Nothing is printed to the console: the bundle goes through standard input.
        $encoded | gh secret set WINDOWS_SIGNING_BUNDLE_BASE64 --repo $Repository --env $Environment
        if ($LASTEXITCODE -ne 0) { throw 'GitHub secret upload failed. Local certificate retained for recovery.' }
        $published = $true
    }
} finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
    if ($published) {
        # -DeleteKey: the private key leaves this PC too, not only the certificate entry.
        Remove-Item "Cert:\CurrentUser\My\$($cert.Thumbprint)" -DeleteKey -ErrorAction SilentlyContinue
    } else {
        Write-Warning "Upload not confirmed. Local certificate retained in CurrentUser/My (thumbprint: $($cert.Thumbprint))."
    }
}
if (-not $published) { throw 'Certificate publication not confirmed' }
if (-not $Throwaway) {
    $sha256 = [BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash($cert.RawData)).Replace('-', '').ToLower()
    Write-Host "Code-signing bundle stored as one secret of the environment $Environment (main only)."
    Write-Host "Certificate SHA-256 (SIGNERS / Signers): $sha256"
}
