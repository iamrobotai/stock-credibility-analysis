#!/usr/bin/env bash
# ============================================================================
#  build_apk_wsl.sh  —  在 WSL (Ubuntu) 内无人值守构建 Android APK
# ============================================================================
#  本脚本由总脚本 setup_and_build_apk.ps1 在「重启登录后」以 root 自动调用，
#  亦支持手动在 WSL 内运行：  wsl -d Ubuntu -u root bash -c 'bash /mnt/c/.../android/build_apk_wsl.sh'
#  前置（已由总脚本完成）：WSL2 + Ubuntu 已装、项目在 /mnt/c/... 下可见。
#  产物：android/bin/*-debug.apk（构建日志同时写到 android/build_log_*.txt）
# ============================================================================

set -euo pipefail

echo "==> [0/6] 环境检查"
UNAME="$(uname -a)"
if ! echo "$UNAME" | grep -qi "microsoft\|linux"; then
  echo "错误：本脚本必须在 WSL / Linux 中运行（当前: $UNAME）" >&2
  exit 1
fi
# root 直跑则无需 sudo；普通用户需 sudo（总脚本以 root 调用，故通常跳过）
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
command -v sudo >/dev/null || { [ "$(id -u)" -eq 0 ] || { echo "需要 sudo，请先完成 Ubuntu 用户初始化" >&2; exit 1; }; }

# ---- 定位项目根目录（WSL 挂载 Windows 盘为 /mnt/c） ----
PROJECT=""
for cand in \
  "/mnt/c/Users/outzb/WorkBuddy/Claw/stock-credibility-analysis" \
  "/mnt/c/users/outzb/WorkBuddy/Claw/stock-credibility-analysis" \
  "$PWD/.." ; do
  if [ -f "$cand/android/buildozer.spec" ]; then PROJECT="$cand"; break; fi
done
if [ -z "$PROJECT" ]; then
  echo "错误：未能自动定位项目根目录（含 android/buildozer.spec）。请手动 cd 到项目根后重跑，或修改本脚本 PROJECT 变量。" >&2
  exit 1
fi
PROJECT="$(cd "$PROJECT" && pwd)"
echo "     项目根目录 = $PROJECT"

echo "==> [1/6] 安装系统依赖 (JDK17 / 构建工具)"
$SUDO apt-get update -y
$SUDO apt-get install -y --no-install-recommends \
  git zip unzip openjdk-17-jdk python3-venv python3-pip \
  autoconf libtool pkg-config zlib1g-dev libncurses5-dev \
  libffi-dev libssl-dev ccache

export JAVA_HOME="/usr/lib/jvm/java-17-openjdk-amd64"
export PATH="$JAVA_HOME/bin:$PATH"
echo "     JAVA_HOME=$JAVA_HOME"
java -version 2>&1 | head -2

echo "==> [2/6] 创建独立 venv 并安装 buildozer + cython (避开 PEP668)"
VENV="$HOME/.buildozer-venv"
if [ ! -x "$VENV/bin/buildozer" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip wheel
  "$VENV/bin/pip" install "cython==0.29.36" "buildozer==1.5.2"
fi
# 当前 shell 启用 venv
source "$VENV/bin/activate"
buildozer --version

echo "==> [3/6] Android SDK / NDK 由 buildozer 首次自动下载到 ~/.buildozer"
# 若你已手动装好 SDK，可取消下一行注释以复用（需为 Linux 版 NDK，Windows NDK 不通用）：
# export ANDROID_HOME="$HOME/Android/Sdk"
mkdir -p "$HOME/.buildozer"

echo "==> [4/6] 进入 android 目录"
cd "$PROJECT/android"
ls -l buildozer.spec

echo "==> [5/6] 构建 debug APK（首次会下载 SDK/NDK 数 GB，请耐心等待 20~40 分钟）"
# yes | 自动接受 SDK license 交互提示
LOGTMP="/tmp/buildozer_$(date +%Y%m%d_%H%M).log"
LOGWIN="$PROJECT/android/build_log_$(date +%Y%m%d_%H%M).txt"
yes | buildozer android debug 2>&1 | tee "$LOGTMP"
# 同步日志到 Windows 侧，便于重启后不进 WSL 也能查看进度
cp "$LOGTMP" "$LOGWIN" 2>/dev/null || true
echo "    构建日志（Windows 侧）： $LOGWIN"

echo "==> [6/6] 完成，查找产物 APK"
APK="$(ls -1 "$PROJECT/android/bin"/*.apk 2>/dev/null | head -1 || true)"
if [ -n "$APK" ]; then
  echo "✅ APK 已生成："
  ls -lh "$PROJECT/android/bin"/*.apk
  echo ""
  echo "安装到已连接设备/模拟器："
  echo "  buildozer android deploy run"
  echo "或手动："
  echo "  adb install \"$APK\""
else
  echo "❌ 未找到 APK，构建可能失败。请查看上方日志 /tmp/buildozer_*.log" >&2
  exit 1
fi
