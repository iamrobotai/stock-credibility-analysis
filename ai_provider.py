# -*- coding: utf-8 -*-
"""
ai_provider.py — 多 AI 提供商统一抽象层
支持: ollama(本地) / deepseek / qwen(通义千问) / openai / zhipu(智谱GLM)
统一接口: call_ai(messages, provider, config) → (text, stats)

配置文件: ai_config.json
{
  "active_provider": "ollama",
  "providers": {
    "ollama":   {"url": "http://localhost:11434", "model": "qwen3:4b"},
    "deepseek": {"api_key": "", "model": "deepseek-chat"},
    "qwen":     {"api_key": "", "model": "qwen-plus"},
    "openai":   {"api_key": "", "model": "gpt-4o-mini"},
    "zhipu":    {"api_key": "", "model": "glm-4-flash"}
  }
}
"""
import json, os, time, sys
from pathlib import Path
import requests

CONFIG_FILE = Path(__file__).parent / "ai_config.json"

# 默认配置
DEFAULT_CONFIG = {
    "active_provider": "ollama",
    "providers": {
        "ollama": {
            "url": "http://localhost:11434",
            "model": "qwen3:4b",
            "label": "Ollama (本地)",
            "note": "零 token，需本地安装 Ollama",
        },
        "deepseek": {
            "api_key": "",
            "model": "deepseek-chat",
            "url": "https://api.deepseek.com/v1",
            "label": "DeepSeek",
            "note": "深度求索 API，性价比高",
        },
        "qwen": {
            "api_key": "",
            "model": "qwen-plus",
            "url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "label": "通义千问",
            "note": "阿里 DashScope API",
        },
        "openai": {
            "api_key": "",
            "model": "gpt-4o-mini",
            "url": "https://api.openai.com/v1",
            "label": "OpenAI",
            "note": "需海外网络",
        },
        "zhipu": {
            "api_key": "",
            "model": "glm-4-flash",
            "url": "https://open.bigmodel.cn/api/paas/v4",
            "label": "智谱 GLM",
            "note": "清华系，免费额度多",
        },
    },
}

_config = None


def load_config():
    global _config
    if _config is not None:
        return _config
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                _config = json.load(f)
            # 合并缺失的 provider
            for k, v in DEFAULT_CONFIG["providers"].items():
                if k not in _config.get("providers", {}):
                    _config.setdefault("providers", {})[k] = v
        except Exception:
            _config = json.loads(json.dumps(DEFAULT_CONFIG))
    else:
        _config = json.loads(json.dumps(DEFAULT_CONFIG))
        save_config()
    return _config


def save_config(cfg=None):
    global _config
    if cfg:
        _config = cfg
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(_config, f, ensure_ascii=False, indent=2)


def get_active_provider():
    cfg = load_config()
    return cfg.get("active_provider", "ollama")


def set_active_provider(name):
    cfg = load_config()
    if name in cfg["providers"]:
        cfg["active_provider"] = name
        save_config(cfg)


def list_providers():
    cfg = load_config()
    result = []
    for key, val in cfg["providers"].items():
        result.append({
            "id": key,
            "label": val.get("label", key),
            "model": val.get("model", ""),
            "note": val.get("note", ""),
            "active": key == cfg.get("active_provider"),
            "needs_key": key != "ollama",
            "has_key": bool(val.get("api_key")),
        })
    return result


# ── 各提供商调用实现 ──

def _call_ollama(messages, provider_cfg, **kwargs):
    """Ollama chat API"""
    url = provider_cfg.get("url", "http://localhost:11434")
    model = provider_cfg.get("model", "qwen3:4b")
    use_json = kwargs.get("format_json", True)
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": kwargs.get("temperature", 0.2),
                     "num_predict": kwargs.get("max_tokens", 600)},
    }
    if use_json:
        payload["format"] = "json"
    r = requests.post(f"{url}/api/chat", json=payload, timeout=kwargs.get("timeout", 120))
    data = r.json()
    content = data.get("message", {}).get("content", "")
    stats = {
        "tokens": data.get("eval_count", 0),
        "duration_s": data.get("eval_duration", 0) / 1e9,
        "tps": data.get("eval_count", 0) / max(data.get("eval_duration", 1) / 1e9, 0.01),
    }
    return content, stats


def _call_openai_compat(messages, provider_cfg, **kwargs):
    """OpenAI 兼容接口 (deepseek/qwen/openai/zhipu 通用)"""
    url = provider_cfg.get("url", "https://api.openai.com/v1")
    api_key = provider_cfg.get("api_key", "")
    model = provider_cfg.get("model", "")
    use_json = kwargs.get("format_json", True)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": kwargs.get("temperature", 0.2),
        "max_tokens": kwargs.get("max_tokens", 600),
    }
    if use_json:
        payload["response_format"] = {"type": "json_object"}

    r = requests.post(f"{url}/chat/completions", json=payload,
                       headers=headers, timeout=kwargs.get("timeout", 60))
    data = r.json()

    if "error" in data:
        raise Exception(data["error"].get("message", str(data["error"])))

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage", {})
    stats = {
        "tokens": usage.get("total_tokens", 0),
        "duration_s": 0,
        "tps": 0,
    }
    return content, stats


def call_ai(messages, provider=None, config=None, **kwargs):
    """
    统一 AI 调用接口
    messages: [{"role":"system","content":"..."}, {"role":"user","content":"..."}]
    provider: 提供商 id (None=使用 active_provider)
    config: 配置 dict (None=使用文件配置)
    返回: (content_str, stats_dict)
    """
    if config is None:
        config = load_config()
    if provider is None:
        provider = config.get("active_provider", "ollama")

    providers = config.get("providers", {})
    if provider not in providers:
        raise ValueError(f"未知 AI 提供商: {provider}")

    provider_cfg = providers[provider]

    # 检查 API key (ollama 不需要)
    if provider != "ollama" and not provider_cfg.get("api_key"):
        raise ValueError(f"提供商 {provider} 未配置 API Key")

    t0 = time.time()
    if provider == "ollama":
        content, stats = _call_ollama(messages, provider_cfg, **kwargs)
    else:
        content, stats = _call_openai_compat(messages, provider_cfg, **kwargs)

    if not stats.get("duration_s"):
        stats["duration_s"] = time.time() - t0
    if not stats.get("tps") and stats.get("tokens"):
        stats["tps"] = stats["tokens"] / max(stats["duration_s"], 0.01)

    stats["provider"] = provider
    stats["model"] = provider_cfg.get("model", "")
    return content, stats


def test_provider(provider=None):
    """测试提供商连通性"""
    try:
        content, stats = call_ai(
            [{"role": "user", "content": "回复JSON: {\"ok\":true}"}],
            provider=provider,
            max_tokens=50,
            format_json=True,
            timeout=30,
        )
        return {"ok": True, "response": content[:200], "stats": stats}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


if __name__ == "__main__":
    # 测试
    print("可用 AI 提供商:")
    for p in list_providers():
        status = "✅" if p["active"] else "  "
        key = "有Key" if p["has_key"] else ("无需" if not p["needs_key"] else "无Key")
        print(f"  {status} {p['id']:10s} | {p['label']:15s} | model={p['model']:20s} | {key}")
    print()

    # 测试 active provider
    active = get_active_provider()
    print(f"测试 active provider: {active}")
    result = test_provider()
    print(f"  {'✅' if result['ok'] else '❌'} {result.get('response', result.get('error', ''))[:100]}")
