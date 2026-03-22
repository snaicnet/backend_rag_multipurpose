param(
    [string]$Region = "ap-southeast-1",
    [string]$AccountId = "961341555117",
    [string]$RepositoryPrefix = "snaic_website",
    [string]$Cluster = "snaic_website_cluster",
    [string]$Service = "backend-rag-multipurpose",
    [int]$DesiredCount = 1,
    [int]$TimeoutMinutes = 20,
    [int]$PollSeconds = 15,
    [string]$TaskDefinitionPath = "deploy/ecs/task-definition.json",
    [switch]$SkipBuild,
    [switch]$SkipPush,
    [switch]$SkipRegister,
    [switch]$SkipUpdate
)

$ErrorActionPreference = "Stop"

$ecrBase = "$AccountId.dkr.ecr.$Region.amazonaws.com/$RepositoryPrefix"
$backendImage = "$ecrBase/rag-backend:latest"
$nginxImage = "$ecrBase/rag-nginx:latest"
$postgresImage = "$ecrBase/rag-postgres:latest"
$taskDefinitionArn = $null

function Get-EcsServiceState {
    param(
        [string]$RegionValue,
        [string]$ClusterValue,
        [string]$ServiceValue
    )

    $raw = aws ecs describe-services --region $RegionValue --cluster $ClusterValue --services $ServiceValue --output json
    if (-not $raw) {
        throw "Failed to describe ECS service."
    }

    $parsed = $raw | ConvertFrom-Json
    if (-not $parsed.services -or $parsed.services.Count -eq 0) {
        throw "ECS service '$ServiceValue' was not found in cluster '$ClusterValue'."
    }

    return $parsed.services[0]
}

function Write-EcsServiceSummary {
    param(
        $ServiceState
    )

    $primaryDeployment = $ServiceState.deployments | Where-Object { $_.status -eq "PRIMARY" } | Select-Object -First 1
    $activeDeploymentCount = @($ServiceState.deployments | Where-Object { $_.status -ne "INACTIVE" }).Count
    $rolloutState = if ($primaryDeployment) { $primaryDeployment.rolloutState } else { "unknown" }
    $rolloutReason = if ($primaryDeployment -and $primaryDeployment.rolloutStateReason) { $primaryDeployment.rolloutStateReason } else { "" }

    Write-Host ("ECS state: running={0} desired={1} pending={2} activeDeployments={3} rollout={4}" -f `
        $ServiceState.runningCount,
        $ServiceState.desiredCount,
        $ServiceState.pendingCount,
        $activeDeploymentCount,
        $rolloutState)

    if ($rolloutReason) {
        Write-Host ("Primary rollout reason: {0}" -f $rolloutReason)
    }
}

function Write-EcsServiceEvents {
    param(
        $ServiceState,
        [int]$MaxEvents = 5
    )

    Write-Host "Recent ECS service events:"
    $ServiceState.events | Select-Object -First $MaxEvents | ForEach-Object {
        Write-Host ("- {0}" -f $_.message)
    }
}

Write-Host "Using region: $Region"
Write-Host "Using ECS cluster: $Cluster"
Write-Host "Using ECS service: $Service"

if (-not $SkipBuild) {
    Write-Host "Building Docker images..."
    docker build -f backend/Dockerfile -t rag-backend:latest backend
    docker build -f backend/nginx/Dockerfile -t rag-nginx:latest backend/nginx
    docker build -f backend/postgres/Dockerfile -t rag-postgres:latest backend
}

if (-not $SkipPush) {
    Write-Host "Logging Docker into ECR..."
    aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin "$AccountId.dkr.ecr.$Region.amazonaws.com"

    Write-Host "Tagging images for ECR..."
    docker tag rag-backend:latest $backendImage
    docker tag rag-nginx:latest $nginxImage
    docker tag rag-postgres:latest $postgresImage

    Write-Host "Pushing images to ECR..."
    docker push $backendImage
    docker push $nginxImage
    docker push $postgresImage
}

if (-not $SkipRegister) {
    Write-Host "Registering new ECS task definition revision..."
    $taskDefinitionArn = aws ecs register-task-definition --region $Region --cli-input-json "file://$TaskDefinitionPath" --query "taskDefinition.taskDefinitionArn" --output text
    if (-not $taskDefinitionArn) {
        throw "Failed to register task definition."
    }
    Write-Host "Registered task definition: $taskDefinitionArn"
}

if (-not $SkipUpdate) {
    if (-not $taskDefinitionArn) {
        if ($SkipRegister) {
            throw "Task definition ARN is unavailable because registration was skipped. Remove -SkipRegister or provide a task definition ARN manually."
        }
    }

    Write-Host "Updating ECS service..."
    aws ecs update-service --region $Region --cluster $Cluster --service $Service --task-definition $taskDefinitionArn --desired-count $DesiredCount --force-new-deployment | Out-Null

    Write-Host "Waiting for service stability..."
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while ($true) {
        $serviceState = Get-EcsServiceState -RegionValue $Region -ClusterValue $Cluster -ServiceValue $Service
        Write-EcsServiceSummary -ServiceState $serviceState

        $primaryDeployment = $serviceState.deployments | Where-Object { $_.status -eq "PRIMARY" } | Select-Object -First 1
        $activeDeployments = @($serviceState.deployments | Where-Object { $_.status -ne "INACTIVE" })
        $isStable = (
            $serviceState.runningCount -eq $DesiredCount -and
            $serviceState.pendingCount -eq 0 -and
            $activeDeployments.Count -eq 1 -and
            $primaryDeployment -and
            $primaryDeployment.rolloutState -eq "COMPLETED"
        )

        if ($isStable) {
            break
        }

        if ((Get-Date) -ge $deadline) {
            Write-Host "Timed out waiting for ECS service stability."
            Write-EcsServiceEvents -ServiceState $serviceState
            throw "ECS service did not become stable within $TimeoutMinutes minutes."
        }

        Start-Sleep -Seconds $PollSeconds
    }

    Write-Host "ECS service updated successfully."
}
