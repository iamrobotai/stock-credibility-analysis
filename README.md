# 股票可信度分析系统

> 本地零 Token 运行的 A 股多维度可信度分析工具，覆盖 20 个行业、175+ 只股票，集成多 AI 提供商深度分析。

## 功能概览

### 核心能力

| 模块 | 说明 |
|------|------|
| **实时热门推荐** | 东财热度榜 + 涨幅榜 + 主力净流入榜 + 行业涨幅排行，2 分钟自动刷新 |
| **股票代码自动解析** | 输入代码 → 自动获取名称、行业（一级+二级）、地域 |
| **多 AI 提供商** | Ollama / **LM Studio** (本地零Token) / DeepSeek / 通义千问 / OpenAI / 智谱GLM，统一接口自由切换，**自动检测已加载模型** |
| **15 平台数据采集** | K线/新闻/研报/财务/公告/互动易/同花顺/资金流/龙虎榜/雪球基本面/**雪球讨论帖**/**知乎**/评论/股吧/淘股吧 |
| **浏览器抓取** | 通过 Playwright 驱动本地浏览器抓取雪球/知乎等需登录或有反爬限制的数据源 |
| **增量更新** | 记录上次采集位置，下次仅获取新数据，合并已有数据，无需从头重新抓取 |
| **自定义保存路径** | 支持自定义数据保存目录，灵活管理存储位置 |
| **情绪帖过滤** | 自动识别并过滤喊单帖、情绪化帖子，保留含实质内容的高价值帖子 |
| **D1-D8 八维评分** | 规则引擎评分 + LLM 深度分析，生成完整 Word 报告 |
| **技术指标** | 14 种技术指标 (MACD/KDJ/RSI/BOLL/CCI/WR/ATR 等) + 50+ K线形态识别 + D9 技术信号评分 |

### 分析维度 (D1-D8)

| 维度 | 名称 | 说明 |
|------|------|------|
| D1 | 来源可信度 | 官方公告 > 研报 > 新闻 > 股吧 |
| D2 | 时间衰减 | 越新的信息权重越高 |
| D3 | 量化匹配 | 价格走势与帖子内容的量化对应 |
| D4 | 情绪极性 | 正面/负面/中性情绪分析 |
| D5 | 机构一致度 | 多来源信息的交叉验证 |
| D6 | 价格段验证 | 预测与实际价格摆荡腿的匹配度 |
| D7 | 信息密度 | 帖子中硬数据（营收/净利/订单）的密度 |
| D8 | 广告甄别 | 关键词库检测 + LLM 二次确认 |

## 系统架构

```
┌─────────────────────────────────────────────────────┐
│                   Flask Web 应用                     │
│            http://localhost:5000                     │
├─────────┬───────────┬───────────┬───────────────────┤
│ 热门推荐  │ 代码解析   │ AI 配置   │  数据源平台选择    │
├─────────┴───────────┴───────────┴───────────────────┤
│                    分析流水线                         │
├──────────┬──────────┬──────────┬──────────┬─────────┤
│ 数据采集  │ 价格分段  │ D1-D8评分 │ LLM增强  │ 报告生成 │
│ (15平台) │ (摆荡腿)  │ (规则引擎)│ (多AI)   │ (docx)  │
└──────────┴──────────┴──────────┴──────────┴─────────┘
```

### 数据流水线

```
股票代码 → stock_resolver (名称/行业)
         → data_collector (13平台采集, ~1200数据点/股)
         → segment (摆荡腿价格分段)
         → score_rules (D1-D8 规则评分)
         → technical (D9 技术指标评分)
         → llm_enhance (AI 深度分析, JSON输出)
         → gen_docx_full (12章节 Word 报告)
```

## 快速部署

### 环境要求

- **Python**: 3.10+ (推荐 3.13)
- **OS**: Windows / macOS / Linux
- **RAM**: 8GB+ (使用 Ollama 本地 AI 时建议 16GB+)
- **GPU**: 可选 (Ollama 本地推理加速)

### 1. 克隆项目

```bash
git clone https://github.com/<your-username>/stock-credibility-analysis.git
cd stock-credibility-analysis
```

### 2. 安装 Python 依赖

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置 AI 提供商 (可选)

#### 方案 A: Ollama 本地 AI (推荐, 零 Token)

```bash
# 安装 Ollama: https://ollama.com/download
# 拉取模型
ollama pull qwen3:4b

# 启动 Ollama 服务
ollama serve
```

#### 方案 B: LM Studio 本地 AI (零 Token)

```bash
# 安装 LM Studio: https://lmstudio.ai/
# 1. 在 LM Studio 中下载所需模型 (如 Qwen3.5-9B)
# 2. 点击 "Start Server" 启动本地 API 服务 (默认端口 1234)
# 3. 在 Web 界面中选择 "LM Studio" 提供商，点击"检测模型"自动获取已加载模型
```

#### 方案 C: 云端 API (需 API Key)

在 Web 界面中配置，或手动编辑 `ai_config.json`:

```json
{
  "active_provider": "deepseek",
  "providers": {
    "deepseek": {
      "api_key": "你的API Key",
      "model": "deepseek-chat",
      "url": "https://api.deepseek.com/v1"
    }
  }
}
```

支持的 AI 提供商:

| 提供商 | 模型 | URL | 说明 |
|--------|------|-----|------|
| Ollama | qwen3:4b | http://localhost:11434 | 本地零 Token，自动检测已安装模型 |
| **LM Studio** | (自动检测) | http://localhost:1234/v1 | 本地零 Token，自动检测已加载模型 |
| DeepSeek | deepseek-chat | https://api.deepseek.com/v1 | 性价比高 |
| 通义千问 | qwen-plus | https://dashscope.aliyuncs.com/compatible-mode/v1 | 阿里云 |
| OpenAI | gpt-4o-mini | https://api.openai.com/v1 | 需海外网络 |
| 智谱GLM | glm-4-flash | https://open.bigmodel.cn/api/paas/v4 | 免费额度多 |

### 4. 启动系统

```bash
python app.py
```

浏览器访问: **http://localhost:5000**

#### Windows 一键启动

双击 `启动分析系统.bat` 即可自动启动并打开浏览器。

## 使用指南

### 单只股票分析

1. 在「实时热门推荐」中点击热门股票，或在「分析任务」中输入股票代码
2. 点击「解析」自动获取名称和行业
3. 选择 AI 提供商和数据源平台
4. 点击「开始分析」
5. 等待流水线完成后下载 Word 报告

### 批量分析

1. 切换到「批量」模式
2. 输入股票列表 JSON: `[{"code":"002371"}, {"code":"300308"}]`
3. 点击「批量解析」自动填充名称/行业
4. 开始分析，完成后打包下载 ZIP

### 行业全量分析

切换到「行业全量」模式，系统将自动加载 20 个行业 × 9 只公司 = 180 只股票的完整列表。

### 数据源平台说明

| 分类 | 平台 | 价值等级 | 说明 |
|------|------|----------|------|
| 核心 | K线行情 | 不可关闭 | 新浪全历史日线数据 |
| 核心 | 东财新闻 | 不可关闭 | 公司相关新闻 |
| 核心 | 东财研报 | 不可关闭 | 券商研究报告 |
| 核心 | 东财财务 | 不可关闭 | 财务报表数据 |
| 高价值 | 巨潮公告 | 推荐 | 交易所官方公告 |
| 高价值 | 互动易 | 推荐 | 投资者问答 |
| 高价值 | 同花顺 | 推荐 | 综合资讯 |
| 高价值 | 资金流 | 推荐 | 主力资金动向 |
| 高价值 | 龙虎榜 | 推荐 | 游资/机构席位 |
| 高价值 | 雪球 | 推荐 | 专业投资者社区 |
| 高价值 | 评论 | 推荐 | 市场情绪参考 |
| 情绪 | 股吧 | 可选 | 散户情绪帖子 |
| 情绪 | 淘股吧 | 可选 | 短线交易讨论 |

启用「过滤情绪帖」可自动剔除股吧/淘股吧中的纯喊单帖，仅保留含实质关键词（营收/净利/订单/合同等）的帖子。

## API 文档

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Web 界面 |
| `/api/hot` | GET | 实时热门股票与行业 |
| `/api/resolve/<code>` | GET | 股票代码解析 |
| `/api/platforms` | GET | 数据源平台列表 (15 个，含雪球讨论帖/知乎) |
| `/api/ai/providers` | GET | AI 提供商列表 |
| `/api/ai/config` | GET/POST | 获取/设置 AI 配置 |
| `/api/ai/test` | POST | 测试 AI 连通性 |
| `/api/ai/models/<provider>` | GET | 自动检测本地 AI 已加载模型 (Ollama/LM Studio) |
| `/api/run` | POST | 启动分析任务 (支持 use_browser/incremental/data_outdir 参数) |
| `/api/status/<run_id>` | GET | 查询任务进度 |
| `/api/stop/<run_id>` | POST | 停止任务 |
| `/api/stocks` | GET | 已有报告列表 |
| `/api/preview/<code>` | GET | 股票分析数据在线预览 |
| `/api/technical/<code>` | GET | 14种技术指标 + K线形态数据 |
| `/api/chart/<code>` | GET | 股票价格走势图 PNG |
| `/api/export/excel/<code>` | GET | 生成并下载 Excel 报告 |
| `/api/industry/chart` | POST | 行业多股走势叠加图 |
| `/api/industry/preview` | GET | 行业对比预览数据 |
| `/api/data/savepath` | GET/POST | 获取/设置数据保存路径 |
| `/api/data/browser-test` | POST | 检测浏览器抓取 (Playwright) 是否可用 |
| `/api/data/browser-fetch` | POST | 手动触发浏览器抓取 (雪球/知乎) |
| `/api/data/incremental` | GET | 获取所有股票增量更新状态摘要 |
| `/api/data/incremental/<code>` | GET/DELETE | 查看/清除指定股票增量更新记录 |
| `/download/<filename>` | GET | 下载报告文件 |

## 项目结构

```
stock-credibility-analysis/
├── app.py                      # Flask Web 应用主入口 (v2.6)
├── ai_config.json              # AI 配置文件 (gitignore, 自动生成)
├── ai_config.example.json      # AI 配置示例 (提交到仓库)
├── requirements.txt            # Python 依赖
├── README.md
├── LICENSE
├── .gitignore
├── 启动分析系统.bat             # Windows 一键启动
├── templates/
│   └── index.html              # Web 前端界面 (v2.6)
├── core/                       # 核心分析模块
│   ├── stock_resolver.py       # 股票代码自动解析
│   ├── data_collector.py       # 15 平台数据采集器 (含雪球讨论帖/知乎)
│   ├── collectors.py           # 扩展平台采集器
│   ├── browser_login.py       # 本地浏览器+人机协同登录爬取 (雪球/知乎/淘股吧, 优先复用系统Chrome)
│   ├── browser_fetcher.py      # 旧版浏览器抓取模块 (已弃用, 保留兼容)
│   ├── incremental_manager.py  # 增量更新管理器
│   ├── segment.py              # 摆荡腿价格分段算法
│   ├── score_rules.py          # D1-D8 规则评分引擎
│   ├── technical.py            # 14种技术指标 + K线形态识别
│   └── hot_stocks.py           # 实时热门股票与行业推荐
├── ai/                         # AI 提供商模块
│   ├── ai_provider.py          # 多 AI 抽象层 (Ollama/LM Studio/云端)
│   └── llm_enhance.py          # LLM 深度分析模块
├── export/                     # 报告生成模块
│   ├── chart_gen.py            # 图表生成 (个股走势/行业叠加)
│   ├── gen_docx_full.py        # Word 报告生成器 (12章节)
│   ├── gen_excel.py            # Excel 报告生成器
│   └── gen_per_company.py      # 按公司生成报告
├── scripts/                    # 工具脚本
│   ├── pipeline.py             # 单行业流水线编排
│   ├── run_all_20.py           # 20 行业全量配置
│   └── ...                     # 其他测试/调试脚本
├── configs/                    # 行业配置文件
├── data/                       # 运行时数据 (gitignore, 自动创建)
├── output/                     # 生成报告 (gitignore, 自动创建)
└── docs/                       # 分析文档 (gitignore)
```

## 技术细节

### 数据采集

- **15 平台采集**: K线/新闻/研报/财务/公告/互动易/同花顺/资金流/龙虎榜/雪球基本面/雪球讨论帖/知乎/评论/股吧/淘股吧
- **K线数据**: 新浪财经 `stock_zh_a_daily` 接口，全历史日线数据
- **多 CDN 容错**: push2 API 支持 5 个 CDN 节点自动切换 (82/48/18/56/default)
- **新浪备用**: 涨幅榜和行业排行使用新浪 API 作为 push2 限流时的备用源
- **超时保护**: 热门数据接口使用线程 + 10 秒超时保护，防止 push2 API 卡死
- **缓存机制**: 热门数据 2 分钟缓存，股票解析结果持久化缓存
- **浏览器抓取**: 雪球讨论帖/知乎通过 Playwright 驱动本地浏览器抓取，应对反爬限制
- **API 备用**: 浏览器抓取失败时自动回退到 API 方式，确保数据可用性

### 浏览器抓取 (Playwright)

- **雪球讨论帖**: `fetch_xueqiu_posts()` - 抓取雪球个股社区讨论帖
- **知乎搜索**: `fetch_zhihu_search()` - 抓取知乎相关问答与文章
- **东财股吧(浏览器)**: `fetch_guba_browser()` - 应对验证码场景
- **通用抓取**: `fetch_page()` - 自定义 URL + CSS 选择器
- **Cookie 缓存**: 首次访问后自动保存 Cookie，后续抓取复用登录态
- **安装**: `pip install playwright && playwright install chromium`

### 增量更新

- **状态管理**: `incremental_manager.py` 记录每只股票每个平台的采集位置
- **去重合并**: 新数据与旧数据按标题去重合并，避免重复
- **恢复点**: 记录上次页码、帖子 ID、时间戳，从上次位置继续
- **API 端点**: `/api/data/incremental` 查看状态，`/api/data/incremental/<code>` 查看/清除

### 价格分段算法

采用摆荡腿(Swing Leg)分段算法:
- 固定锚点，反向波动超过阈值(默认 0.35%)时切换相位
- 输出波段 JSON + 价格曲线 PNG
- 用于 D6 维度的预测验证

### LLM 深度分析

- **Ollama**: `think=false` + `format=json` + `num_predict=1500`，自动检测已安装模型
- **LM Studio**: OpenAI 兼容接口，自动检测已加载模型，零 Token 消耗
- **云端 API**: OpenAI 兼容协议 (DeepSeek/通义千问/OpenAI/智谱)，统一 `call_ai()` 接口
- 输出结构化 JSON: 总体评价 + 风险提示 + 催化剂 + 广告甄别 + D1-D8 LLM 评价

### Word 报告

12 章节完整版报告:
- §0 强提醒门禁 (D8 广告风险置顶)
- §1-§8 D1-D8 各维度详细分析
- §LLM AI 深度分析章节
- §F 财务数据附录

## 已知限制

1. **东财股吧**: 批量采集 175+ 只股票后可能触发验证码拦截
2. **push2 API**: 高频请求时可能被临时限流，系统自动切换 CDN 节点或新浪备用源
3. **非交易时段**: 热门数据为上一交易日收盘数据
4. **Ollama**: 首次拉取模型需 ~3GB 磁盘空间

## License

MIT License - 详见 [LICENSE](LICENSE)

## 免责声明

本系统仅提供信息聚合和分析工具，不构成任何投资建议。股票市场有风险，投资需谨慎。所有数据来源于公开渠道，准确性以官方披露为准。
