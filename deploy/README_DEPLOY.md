# 部署指南（M5 在线一键部署）

本系统提供两种部署形态，按需选择。

---

## 形态一：静态快照（推荐分享 / 只读）

零后端、单文件、可离线，适合把分析结论分享给团队或对外只读展示。

### 生成

```bash
python scripts/export_static_site.py            # 输出 dist_static/index.html
python scripts/export_static_site.py --out <dir>
```

- 读取 `output/quant/*_quant.json` + `summary.json`，把全量标的（当前 176 只）
  的三维结论、策略绩效、风控、持仓结构精简内联进单个 `index.html`（约 300 KB）。
- 页面含：Top 榜单、可搜索/排序全量表、点击查看详情。所有数据已内联，无需任何请求。

### 发布

- **CloudStudio 一键部署**：直接部署 `dist_static/` 目录即可获得分享链接。
  - 最近一次部署链接：`https://80d12c7879e0449c93ec1e3e6d5565df.app.codebuddy.work`
- 也可托管到任意静态服务（Nginx / GitHub Pages / 对象存储），拷贝 `dist_static/` 即可。

### 更新

数据变化后重跑 `scripts/run_quant.py --all` → 再跑 `export_static_site.py` → 重新部署。

---

## 形态二：Flask 动态服务（完整功能）

需要交互式采集、量化实时计算、AI 归因、Word 导出等**动态能力**时使用。

### 本地启动

```bash
python app.py            # http://localhost:5000
# 量化页：http://localhost:5000/quant
```

### 依赖

```bash
pip install -r deploy/requirements.txt
```

### 生产部署（任选）

- **gunicorn（Linux）**：
  ```bash
  gunicorn -w 2 -b 0.0.0.0:5000 app:app
  ```
- **waitress（Windows）**：
  ```bash
  waitress-serve --port=5000 app:app
  ```
- 反向代理（Nginx）转发到上述端口，按需加 Basic Auth / HTTPS。

### 说明

- AI 归因（M4）默认走本地零 Token 提供商（Ollama / LM Studio）；无本地模型时
  自动降级为模板文本，服务不中断。云端提供商需在「AI 设置」填写 API Key。
- 实时数据维度（M3.1：北向/两融/股东/解禁/大宗）依赖 akshare 网络采集，
  部署环境需可访问对应数据源；缺失时结构化降级，不影响主流程。

---

## 里程碑 → 版本映射

| 里程碑 | 内容 | 版本 |
|--------|------|------|
| M4 | LLM 自然语言归因 | v2.9 |
| M5 | 在线一键部署（静态快照 + CloudStudio） | v3.0 |
| M6 | 三维 Word 报告导出 | v3.1 |
