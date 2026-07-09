# 股票可信度分析系统

> 本地零 Token 运行的 A 股多维度可信度分析工具，覆盖 20 个行业、175+ 只股票，集成多 AI 提供商深度分析。

## 功能概览

### 核心能力

| 模块 | 说明 |
|------|------|
| **实时热门推荐** | 东财热度榜 + 涨幅榜 + 主力净流入榜 + 行业涨幅排行，2 分钟自动刷新 |
| **股票代码自动解析** | 输入代码 → 自动获取名称、行业（一级+二级）、地域 |
| **多 AI 提供商** | Ollama(本地零Token) / DeepSeek / 通义千问 / OpenAI / 智谱GLM，统一接口自由切换 |
| **13 平台数据采集** | K线/新闻/研报/财务/公告/互动易/同花顺/资金流/龙虎榜/雪球/股吧/淘股吧/评论 |
| **情绪帖过滤** | 自动识别并过滤喊单帖、情绪化帖子，保留含实质内容的高价值帖子 |
| **D1-D8 八维评分** | 规则引擎评分 + LLM 深度分析，生成完整 Word 报告 |

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
│ (13平台) │ (摆荡腿)  │ (规则引擎)│ (多AI)   │ (docx)  │
└──────────┴──────────┴──────────┴──────────┴─────────┘
```

### 数据流水线

```
股票代码 → stock_resolver (名称/行业)
         → data_collector (13平台采集, ~1200数据点/股)
         → segment (摆荡腿价格分段)
         → score_rules (D1-D8 规则评分)
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

#### 方案 B: 云端 API (需 API Key)

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
| Ollama | qwen3:4b | http://localhost:11434 | 本地零 Token |
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
| `/api/platforms` | GET | 数据源平台列表 |
| `/api/ai/providers` | GET | AI 提供商列表 |
| `/api/ai/config` | GET/POST | 获取/设置 AI 配置 |
| `/api/ai/test` | POST | 测试 AI 连通性 |
| `/api/run` | POST | 启动分析任务 |
| `/api/status/<run_id>` | GET | 查询任务进度 |
| `/api/stop/<run_id>` | POST | 停止任务 |
| `/api/stocks` | GET | 已有报告列表 |
| `/download/<filename>` | GET | 下载报告文件 |

## 项目结构

```
stock-credibility-analysis/
├── app.py                  # Flask Web 应用主入口
├── hot_stocks.py           # 实时热门股票与行业推荐
├── stock_resolver.py       # 股票代码自动解析
├── ai_provider.py          # 多 AI 提供商抽象层
├── ai_config.json          # AI 配置文件 (需自行创建)
├── data_collector.py       # 13 平台数据采集器
├── collectors.py           # 扩展平台采集器 (备用)
├── segment.py              # 摆荡腿价格分段算法
├── score_rules.py          # D1-D8 规则评分引擎
├── llm_enhance.py          # LLM 深度分析模块
├── gen_docx_full.py        # Word 报告生成器
├── pipeline.py             # 单行业流水线编排
├── run_all_20.py           # 20 行业全量配置
├── regen_all.py            # 全量重新生成报告
├── build_chart.py          # 图表生成工具
├── gen_charts.py           # 批量图表生成
├── requirements.txt        # Python 依赖
├── 启动分析系统.bat         # Windows 一键启动
├── templates/
│   └── index.html          # Web 前端界面
├── data/                   # 运行时数据 (自动创建)
└── *.docx                  # 生成的分析报告
```

## 技术细节

### 数据采集

- **K线数据**: 新浪财经 `stock_zh_a_daily` 接口，全历史日线数据
- **多 CDN 容错**: push2 API 支持 5 个 CDN 节点自动切换 (82/48/18/56/default)
- **新浪备用**: 涨幅榜和行业排行使用新浪 API 作为 push2 限流时的备用源
- **缓存机制**: 热门数据 2 分钟缓存，股票解析结果持久化缓存

### 价格分段算法

采用摆荡腿(Swing Leg)分段算法:
- 固定锚点，反向波动超过阈值(默认 0.35%)时切换相位
- 输出波段 JSON + 价格曲线 PNG
- 用于 D6 维度的预测验证

### LLM 深度分析

- Ollama qwen3:4b: `think=false` + `format=json` + `num_predict=1500`
- 云端 API: OpenAI 兼容协议，统一 `call_ai()` 接口
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
