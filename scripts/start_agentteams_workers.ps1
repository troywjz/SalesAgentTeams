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

foreach ($workerName in $workerNames) {
    $state = Get-WorkerState $workerName
    if ($state -eq "missing") {
        Write-Host "等待 AgentTeams 创建 $workerName ..."
        if (-not (Wait-WorkerContainer $workerName $workerTimeoutSeconds)) {
            throw "找不到 Worker 容器：$workerName。请确认 agt apply 已成功。"
        }
        $state = Get-WorkerState $workerName
    }
    if ($state -ne "running") {
        Write-Host "启动 $workerName ..."
        & docker start $workerName | Out-Host
    } elseif (-not (Test-QwenPawApi $workerName)) {
        Write-Host "重启失去 QwenPaw API 的 $workerName ..."
        & docker restart $workerName | Out-Host
    } else {
        Write-Host "$workerName 已运行，QwenPaw API 正常。"
        continue
    }

    if (-not (Wait-WorkerReady $workerName $workerTimeoutSeconds)) {
        Write-Host "--- $workerName 最近日志 ---"
        & docker logs --tail 80 $workerName | Out-Host
        throw "$workerName 未能在 $workerTimeoutSeconds 秒内就绪。"
    }
    Write-Host "$workerName 已就绪。"
}

Write-Host "6 个 AgentTeams Worker 均已通过 Docker + QwenPaw 健康检查。"
