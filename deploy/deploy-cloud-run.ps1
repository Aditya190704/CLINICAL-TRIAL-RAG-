param(
    [string]$ProjectId = "quiet-terminal-422106",
    [string]$Region = "us-central1",
    [string]$ApiService = "clinical-trial-api",
    [string]$WebService = "clinical-trial-web",
    [string]$RuntimeServiceAccount = "",
    [switch]$SkipApiDeploy
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendEnvPath = Join-Path $repoRoot "backend/.env"
$frontendEnvPath = Join-Path $repoRoot "frontend/.env"

function Read-EnvValue([string]$Path, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $line = Get-Content -LiteralPath $Path | Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } | Select-Object -Last 1
    if (-not $line) { return $null }
    return (($line -replace "^\s*$([regex]::Escape($Name))\s*=", "").Trim().Trim('"').Trim("'"))
}

function Invoke-GCloud([string[]]$Arguments) {
    & gcloud @Arguments
    if ($LASTEXITCODE -ne 0) { throw "gcloud failed with exit code ${LASTEXITCODE}: gcloud $($Arguments -join ' ')" }
}

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { throw "Google Cloud CLI (gcloud) is required. Install it and sign in with 'gcloud auth login'." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Node.js and npm are required to build the React frontend." }
if (-not (Test-Path -LiteralPath $frontendEnvPath)) { throw "Missing frontend/.env. Copy frontend/.env.example to frontend/.env and configure the Firebase web app values before deployment." }

$firebaseProjectId = Read-EnvValue $frontendEnvPath "VITE_FIREBASE_PROJECT_ID"
if (-not $firebaseProjectId -or $firebaseProjectId -match "your-|replace|placeholder") { throw "Set VITE_FIREBASE_PROJECT_ID in frontend/.env before deployment." }
foreach ($key in @("VITE_FIREBASE_API_KEY", "VITE_FIREBASE_AUTH_DOMAIN", "VITE_FIREBASE_APP_ID")) {
    if (-not (Read-EnvValue $frontendEnvPath $key)) { throw "Set $key in frontend/.env before deployment." }
}

$dataProjectId = Read-EnvValue $backendEnvPath "GCP_PROJECT"
if (-not $dataProjectId) { $dataProjectId = $ProjectId }
$gcpLocation = Read-EnvValue $backendEnvPath "GCP_LOCATION"
if (-not $gcpLocation) { $gcpLocation = $Region }

Write-Host "Deploy target: $ProjectId ($Region)"
Write-Host "Application data project: $dataProjectId"
Write-Host "Firebase project: $firebaseProjectId"
Write-Host "Checking Google Cloud credentials..."
Invoke-GCloud @("auth", "print-access-token") | Out-Null

Invoke-GCloud @("services", "enable", "run.googleapis.com", "cloudbuild.googleapis.com", "artifactregistry.googleapis.com", "--project", $ProjectId, "--quiet")

if (-not $SkipApiDeploy) {
    $apiArgs = @(
        "run", "deploy", $ApiService,
        "--source", (Join-Path $repoRoot "backend"),
        "--project", $ProjectId,
        "--region", $Region,
        "--platform", "managed",
        "--allow-unauthenticated",
        "--port", "8080",
        "--memory", "2Gi",
        "--cpu", "2",
        "--timeout", "300",
        "--quiet",
        "--set-env-vars", "GCP_PROJECT=$dataProjectId,FIREBASE_PROJECT_ID=$firebaseProjectId,GCP_LOCATION=$gcpLocation"
    )
    if ($RuntimeServiceAccount) { $apiArgs += @("--service-account", $RuntimeServiceAccount) }
    Invoke-GCloud $apiArgs
}
$apiUrl = (& gcloud run services describe $ApiService --project $ProjectId --region $Region --format "value(status.url)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $apiUrl) { throw "Could not read the deployed API URL." }

$frontendPath = Join-Path $repoRoot "frontend"
$buildStage = Join-Path $env:TEMP ("clinical-trial-ui-build-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $buildStage | Out-Null
try {
    foreach ($item in @("package.json", "package-lock.json", "index.html", "vite.config.js", "src", "public")) {
        Copy-Item -LiteralPath (Join-Path $frontendPath $item) -Destination $buildStage -Recurse
    }
    Copy-Item -LiteralPath $frontendEnvPath -Destination (Join-Path $buildStage ".env")
    Push-Location $buildStage
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed in the temporary frontend build directory." }
    $env:VITE_API_BASE_URL = $apiUrl
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed." }
    Pop-Location
    $frontendDist = Join-Path $frontendPath "dist"
    $resolvedFrontend = (Resolve-Path $frontendPath).Path.TrimEnd("\") + "\"
    $resolvedDist = [System.IO.Path]::GetFullPath($frontendDist)
    if (-not $resolvedDist.StartsWith($resolvedFrontend, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace a build output outside the frontend directory."
    }
    if (Test-Path -LiteralPath $frontendDist) { Remove-Item -LiteralPath $frontendDist -Recurse -Force }
    Copy-Item -LiteralPath (Join-Path $buildStage "dist") -Destination $frontendDist -Recurse
} finally {
    Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
    if ((Get-Location).Path -eq $buildStage) { Pop-Location }
    $resolvedTemp = (Resolve-Path $env:TEMP).Path.TrimEnd("\") + "\"
    $resolvedStage = [System.IO.Path]::GetFullPath($buildStage)
    if ($resolvedStage.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedStage -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Invoke-GCloud @(
    "run", "deploy", $WebService,
    "--source", (Join-Path $repoRoot "frontend"),
    "--project", $ProjectId,
    "--region", $Region,
    "--platform", "managed",
    "--allow-unauthenticated",
    "--port", "8080",
    "--memory", "256Mi",
    "--cpu", "1",
    "--quiet"
)
$webUrl = (& gcloud run services describe $WebService --project $ProjectId --region $Region --format "value(status.url)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $webUrl) { throw "Could not read the deployed web URL." }

Invoke-GCloud @("run", "services", "update", $ApiService, "--project", $ProjectId, "--region", $Region, "--update-env-vars", "CORS_ORIGINS=$webUrl")

Write-Host ""
Write-Host "Cloud Run deployment complete."
Write-Host "Web: $webUrl"
Write-Host "API: $apiUrl"
Write-Host "API readiness: $apiUrl/api/ready"
Write-Host "Check that the Cloud Run runtime service account can use Firestore in $firebaseProjectId and BigQuery/Vertex AI in $dataProjectId."
