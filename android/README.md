# Android APK 构建说明

本目录将现有 Flask + Web 应用包装为 Android 安装包（APK）。
**方案**：Kivy + `kivy_garden.webview` 做壳——`main.py` 在后台线程启动本地 Flask 服务，前端 WebView 加载 `http://127.0.0.1:5000/`，业务逻辑 100% 复用项目根目录的 `app.py`，无需重写。

> 📌 **本 APK 加载的就是「合并版单页」**：桌面端已将主仪表盘（可信度分析）与量化分析页合并为 `templates/dashboard.html`，并由 `app.py` 的 `/` 路由渲染。因此移动端 WebView 打开即同时看到**可信度分析 + 量化回测/资金/综合可信度融合**两个分析，不再分 URL。

> ⚠️ **Windows 本机无法直出 APK**。Buildozer 必须在 **Linux 或 WSL（Ubuntu）** 中运行，并安装 Android SDK + NDK。
>
> 🔒 **本仓库所在的这台 Windows 主机当前没有管理员权限**（`net session` → 无权限），因此连 WSL 都无法在此安装——**本机不可能产出真实 `.apk`**。不要伪造 apk。正确路径：在你**有管理员权限**的 Windows 上装好 WSL（见第 0 节），随后一条命令即可出包（见第 3 节 `build_apk_wsl.sh`）。

## 0. 本机前置（需 Windows 管理员，一次性）

本脚本与项目无法替代以下 Windows 侧操作（需要管理员 PowerShell）：

```powershell
# ① 管理员 PowerShell 安装 WSL + Ubuntu
wsl --install -d Ubuntu
# ② 按提示【重启电脑】一次（启用 WSL2 虚拟机平台必须重启）
# ③ 重启后首次启动 Ubuntu，完成 UNIX 用户初始化（仅此一次交互）
```

重启并初始化完成后，本项目在 WSL 中已可直接访问：`/mnt/c/Users/outzb/WorkBuddy/Claw/stock-credibility-analysis`。

## 1. 准备 WSL 环境（Ubuntu 22.04）
```bash
sudo apt update && sudo apt install -y git zip unzip openjdk-17-jdk python3-pip \
  autoconf libtool pkg-config zlib1g-dev libncurses5-dev libffi-dev libssl-dev
pip install --upgrade buildozer cython==0.29.36
```

## 2. 安装 Android SDK / NDK
首次 `buildozer android debug` 会自动下载 SDK/NDK 到 `$HOME/.buildozer`；
或手动设置：
```bash
export ANDROID_HOME=$HOME/Android/Sdk
# 在 SDK Manager 中安装：Platform 33、Build-Tools、NDK 25b
```

## 3. 构建

### 方案 A（推荐，无人值守一条命令）
进入 `android/` 直接运行本仓库附带的脚本，它会自动装依赖、建 venv、装 buildozer、首次自动下载 SDK/NDK 并执行构建：
```bash
cd /mnt/c/Users/outzb/WorkBuddy/Claw/stock-credibility-analysis/android
bash build_apk_wsl.sh
# 产物：android/bin/*-debug.apk
```

### 方案 B（手动分步）
将**整个项目**（含本 `android/` 目录）拷入 WSL，进入 `android/` 执行：
```bash
cd /path/to/stock-credibility-analysis/android

buildozer android debug      # 产出 bin/股票可信度分析系统-1.0.0-debug.apk
# 发布版（需在 buildozer.spec 填入签名 store/alias/密码）
buildozer android release
```
`buildozer.spec` 已配置：`source.dir = ../..` 含 `app.py / core / quant / templates / static / configs` 等；依赖含 `flask / pandas / numpy / akshare`；权限 `INTERNET` 等。

## 4. 安装到设备
```bash
buildozer android deploy run        # 需 adb 已连接设备/模拟器
# 或手动：adb install bin/*.apk
```

## 5. 已知限制
- **体积大**：pandas + numpy + akshare 使 APK 通常 > 50 MB。
- **数据源**：akshare 需访问境内数据接口；境外/受限移动网络可能拉取失败，离线时仅能渲染已落库的 `data/`。
- **首启动慢**：移动端 SoC 上 pandas 初始化与 Flask 冷启动较桌面更慢（数秒到十几秒）。
- **WebView 兼容**：个别 ROM 需系统 WebView 组件支持。

详见根目录 `docs/PACKAGING.md` §6。
