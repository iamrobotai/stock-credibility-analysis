[app]

# (str) 应用标题（桌面/关于页显示）
title = 股票可信度分析系统

# (str) 包名（必须唯一，建议反向域名）
package.name = com.stockcredibility.app

# (str) 应用全名
full.name = StockCredibility

# (str) 入口文件名（本目录的 main.py）
source.dir = ../..

# (str) 入口模块
source.include_exts = py,png,jpg,jpeg,gif,json,html,css,js,ico,ttf
source.include_patterns =
    *.py,
    app.py,
    launcher.py,
    core/*,
    quant/*,
    ai/*,
    export/*,
    services/*,
    common/*,
    annotation/*,
    templates/*,
    static/*,
    configs/*,
    scripts/*
source.exclude_exts = pyc,pyo,pyd,tmp,bak,log
source.exclude_dirs = .git,__pycache__,build,dist,output,data/browser_cookies,data/browser_profiles
source.exclude_patterns = */__pycache__/*,*.pyc

# (str) 入口类名（Kivy App 子类）
app.main = android.main:StockApp

# (str) 应用版本（需递增以覆盖安装）
version = 1.0.0

# (list) 应用要求（权限）
android.permissions = INTERNET,ACCESS_NETWORK_STATE,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

# (int) API 级别
android.api = 33
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24

# (bool) 是否使用 AndroidX
android.enable_androidx = True
android.add_gradle_repositories =
    maven { url 'https://maven.google.com' }

# (list) 需打包进 APK 的 Python 依赖
requirements =
    python3==3.11.9,
    kivy==2.3.1,
    kivy_garden.webview==0.4.1,
    plyer==2.1.0,
    flask==3.1.3,
    jinja2==3.1.6,
    werkzeug==3.1.3,
    markupsafe==2.1.5,
    itsdangerous==2.2.0,
    click==8.1.7,
    blinker==1.9.0,
    pandas==2.2.3,
    numpy==1.26.4,
    akshare==1.18.64,
    requests==2.32.3,
    lxml==5.4.0,
    openpyxl==3.1.5,
    beautifulsoup4==4.12.3,
    html5lib==1.1

# (str) 服务端口（与 app.run / launcher 一致）
# 通过环境变量注入，shell 内已默认 5000
# android.putExtra = "PORT=5000"

# (list) 本地 .so / 库（一般留空，PyInstaller 同款逻辑由 buildozer 处理）
android.add_libs_armeabi_v7a = 
android.add_libs_arm64_v8a = 
android.add_libs_x86 = 
android.add_libs_x86_64 = 

# (bool) 是否编译为 release（签名后分发）
android.release = False

# (str) 签名（release 必须）
# android.signing.store = ~/my-release-key.keystore
# android.signing.alias = myalias
# android.signing.store_password = *****
# android.signing.key_password = *****

# (bool) 是否上传到 Play（本流程不用）
android.upload_to_play_store = False

[buildozer]

# (int) 日志等级
log_level = 2

# (str) buildozer 版本
buildozer.version = 1.5.2

# (list) 构建目标（默认 android debug）
# buildozer.spec 默认目标
default_goal = android_debug
