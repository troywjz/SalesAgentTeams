$ErrorActionPreference = "Stop"

function Initialize-Utf8Console {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $global:OutputEncoding = [System.Text.UTF8Encoding]::new()
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
}

function Get-ProjectRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-RuntimeRoot([string]$ProjectRoot) {
    $runtimeRoot = Join-Path $ProjectRoot ".runtime"
    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    return $runtimeRoot
}

function Read-DotEnv([string]$Path) {
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $values
    }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $value = $Matches[2].Trim()
            if ($value.Length -ge 2) {
                $first = $value.Substring(0, 1)
                $last = $value.Substring($value.Length - 1, 1)
                if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
            }
            $values[$Matches[1]] = $value
        }
    }
    return $values
}

function Get-EnvValue(
    [hashtable]$Values,
    [string]$Name,
    [string]$Default = ""
) {
    if ($Values.ContainsKey($Name) -and -not [string]::IsNullOrWhiteSpace([string]$Values[$Name])) {
        return [string]$Values[$Name]
    }
    return $Default
}

function ConvertTo-Bool([string]$Value, [bool]$Default = $false) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $Default
    }
    return $Value.Trim().ToLowerInvariant() -in @("1", "true", "yes", "on")
}

function Test-DockerEngine {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        return $false
    }
    & cmd.exe /d /c "docker info --format {{.ServerVersion}} >nul 2>nul"
    return ($LASTEXITCODE -eq 0)
}

function Wait-DockerEngine([int]$TimeoutSeconds = 180) {
    if (Test-DockerEngine) {
        return
    }

    $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        throw "未找到 Docker Desktop。请先运行 setup.cmd 安装依赖。"
    }

    Write-Host "正在启动 Docker Desktop ..." -ForegroundColor Cyan
    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden | Out-Null
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        if (Test-DockerEngine) {
            Write-Host "Docker Engine 已就绪。" -ForegroundColor Green
            return
        }
    }
    throw "Docker Engine 在 $TimeoutSeconds 秒内未就绪。请打开 Docker Desktop 检查 WSL 2 或虚拟化配置。"
}

function Invoke-DockerCompose([string[]]$Arguments) {
    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose 执行失败，退出码：$LASTEXITCODE"
    }
}

function Get-ContainerState([string]$Name) {
    if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]+$') {
        throw "非法容器名称：$Name"
    }
    $state = & cmd.exe /d /c "docker inspect $Name --format {{.State.Status}} 2>nul"
    if ($LASTEXITCODE -ne 0) {
        return "missing"
    }
    return ([string]($state | Select-Object -First 1)).Trim()
}

function Wait-ContainerHealthy(
    [string]$Name,
    [int]$TimeoutSeconds = 90
) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $status = & docker inspect $Name --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>$null
        if ($LASTEXITCODE -eq 0 -and ([string]$status).Trim() -in @("healthy", "running")) {
            return
        }
        Start-Sleep -Seconds 2
    }
    & docker logs --tail 80 $Name 2>&1 | Out-Host
    throw "容器 $Name 在 $TimeoutSeconds 秒内未就绪。"
}

function Test-TcpPort([int]$Port, [string]$HostName = "127.0.0.1") {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        if (-not $task.Wait(1500)) {
            return $false
        }
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Wait-TcpPort(
    [int]$Port,
    [string]$Label,
    [int]$TimeoutSeconds = 90
) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpPort -Port $Port) {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "$Label 未在 $TimeoutSeconds 秒内监听 127.0.0.1:$Port。"
}

function Wait-HttpOk(
    [string]$Url,
    [string]$Label,
    [int]$TimeoutSeconds = 90
) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 400) {
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "$Label 健康检查失败：$Url"
}

function Get-ManagedProcessMetadataPath([string]$RuntimeRoot, [string]$Name) {
    return Join-Path $RuntimeRoot "$Name.process.json"
}

function Get-ManagedProcess(
    [string]$RuntimeRoot,
    [string]$Name,
    [string]$ExpectedExecutable
) {
    $metadataPath = Get-ManagedProcessMetadataPath -RuntimeRoot $RuntimeRoot -Name $Name
    if (-not (Test-Path -LiteralPath $metadataPath)) {
        return $null
    }
    try {
        $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $process = Get-Process -Id ([int]$metadata.pid) -ErrorAction Stop
        if ($process.StartTime.ToUniversalTime().Ticks -ne [long]$metadata.start_time_utc_ticks) {
            return $null
        }
        if ($ExpectedExecutable) {
            $actualPath = $process.Path
            if (-not $actualPath -or -not [string]::Equals(
                [IO.Path]::GetFullPath($actualPath),
                [IO.Path]::GetFullPath($ExpectedExecutable),
                [StringComparison]::OrdinalIgnoreCase
            )) {
                return $null
            }
        }
        return $process
    }
    catch {
        return $null
    }
}

function Start-ManagedProcess(
    [string]$RuntimeRoot,
    [string]$Name,
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$WorkingDirectory
) {
    $existing = Get-ManagedProcess -RuntimeRoot $RuntimeRoot -Name $Name -ExpectedExecutable $FilePath
    if ($existing) {
        Write-Host "$Name 已运行（PID $($existing.Id)）。"
        return $existing
    }

    $stdoutLog = Join-Path $RuntimeRoot "$Name.out.log"
    $stderrLog = Join-Path $RuntimeRoot "$Name.err.log"
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru
    Start-Sleep -Milliseconds 800
    if ($process.HasExited) {
        if (Test-Path -LiteralPath $stderrLog) {
            Get-Content -LiteralPath $stderrLog -Tail 80 -Encoding UTF8 | Out-Host
        }
        throw "$Name 启动失败，退出码：$($process.ExitCode)"
    }

    $metadata = [ordered]@{
        name = $Name
        pid = $process.Id
        start_time_utc_ticks = $process.StartTime.ToUniversalTime().Ticks
        executable = [IO.Path]::GetFullPath($FilePath)
        arguments = $ArgumentList
        working_directory = $WorkingDirectory
    }
    $metadata | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (
        Get-ManagedProcessMetadataPath -RuntimeRoot $RuntimeRoot -Name $Name
    ) -Encoding UTF8
    Write-Host "$Name 已启动（PID $($process.Id)）。"
    return $process
}

function Stop-ManagedProcess(
    [string]$RuntimeRoot,
    [string]$Name,
    [string]$ExpectedExecutable
) {
    $metadataPath = Get-ManagedProcessMetadataPath -RuntimeRoot $RuntimeRoot -Name $Name
    $process = Get-ManagedProcess -RuntimeRoot $RuntimeRoot -Name $Name -ExpectedExecutable $ExpectedExecutable
    if ($process) {
        Write-Host "正在停止 $Name（PID $($process.Id)）..."
        & taskkill.exe /PID $process.Id /T /F *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "停止 $Name 进程树失败，退出码：$LASTEXITCODE"
        }
    }
    if (Test-Path -LiteralPath $metadataPath) {
        Remove-Item -LiteralPath $metadataPath -Force
    }
}

function Stop-ProjectPythonFallback(
    [string]$ExpectedExecutable,
    [string[]]$CommandMarkers
) {
    $expected = [IO.Path]::GetFullPath($ExpectedExecutable)
    $processes = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue
    foreach ($process in $processes) {
        if (-not $process.ExecutablePath -or -not [string]::Equals(
            [IO.Path]::GetFullPath($process.ExecutablePath),
            $expected,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            continue
        }
        $matchesProjectCommand = $false
        foreach ($marker in $CommandMarkers) {
            if ([string]$process.CommandLine -like "*$marker*") {
                $matchesProjectCommand = $true
                break
            }
        }
        if ($matchesProjectCommand) {
            Write-Host "停止未登记但属于本项目的 Python 进程（PID $($process.ProcessId)）。"
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}
