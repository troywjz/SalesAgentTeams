$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

# AgentTeams Worker 是容器内再托管 QwenPaw 子进程的两层运行时。
# 因此同时检查 Docker 容器状态和 QwenPaw 管理 API，避免出现“容器 Up 但 Worker 已失效”。
$workerNames = @(
    "agentteams-worker-sales-intent-worker",
    "agentteams-worker-sales-sop-worker",
    "agentteams-worker-sales-knowledge-worker",
    "agentteams-worker-sales-conversation-worker",
    "agentteams-worker-sales-safety-worker",
    "agentteams-worker-sales-memory-worker"
)
$workerTimeoutSeconds = 60
$workerStabilitySeconds = 12
$workerStartAttempts = 2

function Get-WorkerState([string]$Name) {
    $state = & cmd.exe /d /c "docker inspect $Name --format {{.State.Status}} 2>nul"
    if ($LASTEXITCODE -ne 0) {
        return "missing"
    }
    return ($state | Select-Object -First 1).Trim()
}

function Test-QwenPawApi([string]$Name) {
    & docker exec $Name sh -lc "curl -fsS http://127.0.0.1:8088/api/version >/dev/null 2>&1"
    return ($LASTEXITCODE -eq 0)
}

function Wait-WorkerContainer([string]$Name, [int]$TimeoutSeconds = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ((Get-WorkerState $Name) -ne "missing") {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Wait-WorkerReady([string]$Name, [int]$TimeoutSeconds = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $state = Get-WorkerState $Name
        if ($state -eq "running" -and (Test-QwenPawApi $Name)) {
            return $true
        }
        if ($state -eq "exited") {
            return $false
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Test-WorkerStable([string]$Name, [int]$Seconds = 12) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if ((Get-WorkerState $Name) -ne "running" -or -not (Test-QwenPawApi $Name)) {
            return $false
        }
        Start-Sleep -Seconds 2
    }
    return $true
}

foreach ($workerName in $workerNames) {
    $stable = $false
    foreach ($attempt in 1..$workerStartAttempts) {
        $state = Get-WorkerState $workerName
        if ($state -eq "missing") {
            Write-Host "等待 AgentTeams 创建 $workerName ..."
            if (-not (Wait-WorkerContainer $workerName $workerTimeoutSeconds)) {
                break
            }
            $state = Get-WorkerState $workerName
        }
        if ($state -ne "running") {
            Write-Host "启动 $workerName（$attempt/$workerStartAttempts）..."
            & docker start $workerName | Out-Host
        } elseif (-not (Test-QwenPawApi $workerName)) {
            Write-Host "重启失去 QwenPaw API 的 $workerName（$attempt/$workerStartAttempts）..."
            & docker restart $workerName | Out-Host
        }
        if ($LASTEXITCODE -ne 0) {
            continue
        }
        if ((Wait-WorkerReady $workerName $workerTimeoutSeconds) -and (
            Test-WorkerStable $workerName $workerStabilitySeconds
        )) {
            $stable = $true
            break
        }
        Write-Host "$workerName 就绪后未保持稳定，准备重试 ..." -ForegroundColor Yellow
    }
    if (-not $stable) {
        Write-Host "--- $workerName 最近日志 ---"
        & docker logs --tail 80 $workerName | Out-Host
        throw "$workerName 未能通过 Docker + QwenPaw 稳定性检查。"
    }
    Write-Host "$workerName 已通过 $workerStabilitySeconds 秒稳定性检查。"
}

Write-Host "6 个 AgentTeams Worker 均已通过 Docker + QwenPaw 健康检查。"
