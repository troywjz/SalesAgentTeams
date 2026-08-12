# 向后兼容旧入口；完整环境准备逻辑统一维护在 setup_project.ps1。
& (Join-Path $PSScriptRoot "setup_project.ps1") @args
