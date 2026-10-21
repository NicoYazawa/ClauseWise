# AI智能合同合规审查平台 - Windows 启动脚本
# 用法：.\scripts\start.ps1          （API 服务；启动时自动预检 MySQL/ES/Redis/模型 API，任一未就绪直接退出）
#       .\scripts\start.ps1 worker   （Celery Worker，需 Redis；Windows 用 solo 池）
#       .\scripts\start.ps1 beat     （Celery Beat 定时任务）
$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent $PSScriptRoot
Set-Location $backendDir

# 激活 venv（如存在）
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    . .\.venv\Scripts\Activate.ps1
}

$mode = if ($args.Count -gt 0) { $args[0] } else { "api" }

switch ($mode) {
    "worker" {
        Write-Host "[Celery Worker] parse/review/index 三队列（--pool=solo）..." -ForegroundColor Cyan
        celery -A app.tasks.celery_app worker --pool=solo --loglevel=info -Q parse,review,index
    }
    "beat" {
        Write-Host "[Celery Beat] 超时扫描 / 定时任务..." -ForegroundColor Cyan
        celery -A app.tasks.celery_app beat --loglevel=info
    }
    default {
        # Redis 预提示：地址从 .env 的 REDIS_URL 解析（环境差异仅收敛于 .env，换机只改 .env）
        $redisHost = "127.0.0.1"
        $redisPort = 6379
        $redisLine = (Get-Content ".\.env" -Encoding UTF8 -ErrorAction SilentlyContinue) -match '^\s*REDIS_URL\s*=' | Select-Object -First 1
        if ($redisLine -match 'rediss?://([^:/@]+):(\d+)') {
            $redisHost = $Matches[1]
            $redisPort = [int]$Matches[2]
        }

        $redisUp = $false
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect($redisHost, $redisPort)
            $tcp.Close()
            $redisUp = $true
        } catch { }

        if ($redisUp) {
            Write-Host "[OK] Redis($redisHost`:$redisPort) 可用：请另开窗口执行 .\scripts\start.ps1 worker 与 beat" -ForegroundColor Green
        } else {
            Write-Host "[警告] Redis($redisHost`:$redisPort) 不可用：启动预检将失败并直接退出，请先启动 Redis/Memurai 服务" -ForegroundColor Red
        }
        Write-Host "[API] uvicorn http://0.0.0.0:8000  （文档 /docs；启动时自动预检 MySQL/ES/Redis/模型 API，任一未就绪将直接退出）..." -ForegroundColor Cyan
        uvicorn app.main:app --host 0.0.0.0 --port 8000
    }
}
