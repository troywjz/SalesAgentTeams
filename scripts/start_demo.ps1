# 向后兼容旧入口；完整启动逻辑统一维护在 start_all.ps1。
& (Join-Path $PSScriptRoot "start_all.ps1") @args
