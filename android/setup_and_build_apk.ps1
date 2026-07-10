# setup_and_build_apk.ps1
# ============================================================================
#  一步到位：安装 WSL2 + Ubuntu  ->  注册「重启登录后自动构建 APK」任务  ->  重启
#
#  用法：以管理员身份运行（脚本会自动尝试提权；若 UAC 被拒，请手动右键
#        「以管理员身份运行」本文件）。
#  之后：重启电脑 -> 登录 -> 自动开始构建 -> 产物在 android\bin\*.apk
#
#  说明：本机（无管理员权限的受限账户）无法运行本脚本；请在【有管理员权限】
#        的 Windows 上执行。APK 构建本身只能在 WSL/Linux 中进行。
# ============================================================================

# ---- 0) 自提权：若当前不是管理员，重新以管理员启动本脚本 ----
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
    Write-Host "请求管理员权限重新启动本脚本..." -ForegroundColor Yellow
    Start-Process -FilePath (Get-Process -Id $PID).Path -Verb RunAs `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Wait
    exit
}

$ErrorActionPreference = "Stop"
$ProjWin   = "C:\Users\outzb\WorkBuddy\Claw\stock-credibility-analysis"
$AndWin    = "$ProjWin\android"
$ScriptWsl = "/mnt/c/Users/outzb/WorkBuddy/Claw/stock-credibility-analysis/android/build_apk_wsl.sh"
$Distro    = "Ubuntu"
$TaskName  = "StockCredAPKBuild"

function Step($n, $t) { Write-Host "`n==> [$n] $t" -ForegroundColor Cyan }

Step "1/6" "启用 WSL2 + 虚拟机平台（norestart）"
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart | Out-Null
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart | Out-Null
wsl.exe --set-default-version 2 | Out-Null

Step "2/6" "安装 Ubuntu（--no-launch 避免首次交互初始化）"
if (-not (wsl.exe -l | Select-String "Ubuntu")) {
    # 若你的 Windows 版本不支持 --no-launch，去掉该参数即可（首次启动会要求输入用户名/密码一次）
    wsl.exe --install -d Ubuntu --no-launch 2>&1 | Out-String | Write-Host
} else {
    Write-Host "    Ubuntu 已存在，跳过安装"
}

Step "3/6" "写入「登录后自动构建」任务启动器 run_build_task.ps1"
$launcher = @"
# 由 setup_and_build_apk.ps1 自动生成，勿手改
# 以 root 进 WSL 执行构建脚本（root 无需密码，杜绝交互卡死）
wsl.exe -d $Distro -u root bash -c 'bash $ScriptWsl'
# 构建（无论成败）后移除本任务，避免每次登录重复运行
schtasks.exe /delete /tn "$TaskName" /f | Out-Null
"@
Set-Content -Path "$AndWin\run_build_task.ps1" -Value $launcher -Encoding UTF8
Write-Host "    已生成：$AndWin\run_build_task.ps1"

Step "4/6" "注册计划任务（登录时触发，自动以 root 进 WSL 构建）"
schtasks.exe /delete /tn $TaskName /f 2>$null
$act = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$AndWin\run_build_task.ps1`""
schtasks.exe /create /tn $TaskName /tr $act /sc onlogon /rl highest /f | Out-Null
Write-Host "    任务已注册：$TaskName（下次登录后自动开始构建）"

Step "5/6" "校验交付文件齐备"
if ((Test-Path "$AndWin\build_apk_wsl.sh") -and (Test-Path "$AndWin\run_build_task.ps1")) {
    Write-Host "    OK: build_apk_wsl.sh + run_build_task.ps1 就位"
} else {
    Write-Host "    [错误] 缺失构建脚本，请确认仓库完整后重试" -ForegroundColor Red
    exit 1
}

Step "6/6" "重启以完成 WSL 初始化；重启登录后自动构建 APK"
Write-Host "    构建日志（Windows 侧）： $AndWin\build_log_*.txt" -ForegroundColor Yellow
Write-Host "    产物（Windows 侧）：       $AndWin\bin\*.apk" -ForegroundColor Yellow
Write-Host "    若构建失败需重试（免重启）： 在 WSL 中运行  bash $ScriptWsl" -ForegroundColor Yellow
Read-Host "按 Enter 立即重启（或 Ctrl+C 取消）"
Restart-Computer -Force
