# -*- coding: utf-8 -*-
"""
incremental_manager.py -- 增量更新管理器 v1.0
====================================
记录每次数据采集的位置 (页码/时间戳/帖子ID)，下次更新时从上次位置继续。

状态文件: data/incremental_state.json
结构:
{
    "002371": {
        "xueqiu_posts": {
            "last_fetch_time": "2025-07-10T08:00:00",
            "last_page": 2,
            "last_post_id": "XQ-30",
            "last_timestamp": "2025-07-09",
            "total_fetched": 30
        },
        "zhihu": {
            "last_fetch_time": "2025-07-10T08:00:00",
            "last_keyword": "北方华创",
            "total_fetched": 20
        },
        "guba": {
            "last_fetch_time": "2025-07-10T08:00:00",
            "last_page": 3,
            "last_post_title_hash": "a1b2c3d4",
            "total_fetched": 90
        }
    }
}
"""
import os
import json
import hashlib
from pathlib import Path
from datetime import datetime

# 项目根目录自适应
_PROJECT_ROOT = Path(__file__).resolve().parent
while _PROJECT_ROOT.name and not (_PROJECT_ROOT / "data").exists() and _PROJECT_ROOT.parent != _PROJECT_ROOT:
    _PROJECT_ROOT = _PROJECT_ROOT.parent

DATA_DIR = _PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

STATE_FILE = DATA_DIR / "incremental_state.json"


def _load_state():
    """加载增量状态"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(state):
    """保存增量状态"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [incremental] 保存状态失败: {e}")


def get_state(code, platform=None):
    """
    获取股票的增量状态

    Args:
        code: 股票代码
        platform: 平台名 (None=返回所有平台)

    Returns:
        dict: 增量状态
    """
    state = _load_state()
    stock_state = state.get(code, {})
    if platform:
        return stock_state.get(platform, {})
    return stock_state


def update_state(code, platform, **kwargs):
    """
    更新增量状态

    Args:
        code: 股票代码
        platform: 平台名
        **kwargs: 要更新的字段 (last_page, last_post_id, last_timestamp, total_fetched, etc.)

    Example:
        update_state("002371", "xueqiu_posts", last_page=2, last_post_id="XQ-30", total_fetched=30)
    """
    state = _load_state()
    if code not in state:
        state[code] = {}
    if platform not in state[code]:
        state[code][platform] = {}

    state[code][platform].update(kwargs)
    state[code][platform]["last_fetch_time"] = datetime.now().isoformat()

    _save_state(state)


def get_resume_point(code, platform):
    """
    获取恢复点信息

    Returns:
        dict: {last_page, last_post_id, last_timestamp, total_fetched, last_fetch_time}
              如果没有历史记录，返回空 dict
    """
    return get_state(code, platform)


def is_incremental_available(code, platform):
    """检查是否有增量更新记录"""
    state = get_state(code, platform)
    return bool(state and state.get("last_fetch_time"))


def merge_data(old_data, new_data, key_field="title"):
    """
    合并旧数据和新数据 (去重)

    Args:
        old_data: 旧数据列表
        new_data: 新数据列表
        key_field: 去重字段

    Returns:
        tuple: (merged_data, new_count) 合并后的数据和新增数量
    """
    seen = set()
    merged = []

    # 先加入旧数据
    for item in old_data:
        k = item.get(key_field, "") or str(item)
        if k and k not in seen:
            seen.add(k)
            merged.append(item)

    # 加入新数据
    new_count = 0
    for item in new_data:
        k = item.get(key_field, "") or str(item)
        if k and k not in seen:
            seen.add(k)
            merged.append(item)
            new_count += 1
        elif not k:
            merged.append(item)
            new_count += 1

    return merged, new_count


def dedup_by_hash(data, field="title"):
    """
    通过字段哈希去重

    Args:
        data: 数据列表
        field: 去重字段

    Returns:
        list: 去重后的列表
    """
    seen = set()
    result = []
    for item in data:
        val = item.get(field, "")
        h = hashlib.md5(val.encode("utf-8")).hexdigest()[:8] if val else ""
        if h not in seen or not h:
            if h:
                seen.add(h)
            result.append(item)
    return result


def get_all_codes():
    """获取所有有增量记录的股票代码"""
    state = _load_state()
    return list(state.keys())


def get_summary():
    """获取增量更新摘要"""
    state = _load_state()
    summary = {}
    for code, platforms in state.items():
        summary[code] = {
            plat: {
                "last_fetch": info.get("last_fetch_time", ""),
                "total_fetched": info.get("total_fetched", 0),
            }
            for plat, info in platforms.items()
        }
    return summary


def clear_state(code=None, platform=None):
    """
    清除增量状态

    Args:
        code: 股票代码 (None=清除所有)
        platform: 平台名 (None=清除该股票所有平台)
    """
    state = _load_state()
    if code is None:
        state = {}
    elif code in state:
        if platform is None:
            del state[code]
        elif platform in state[code]:
            del state[code][platform]
            if not state[code]:
                del state[code]
    _save_state(state)


if __name__ == "__main__":
    # 测试
    print("=== 增量状态摘要 ===")
    summary = get_summary()
    if not summary:
        print("  (空)")
    for code, plats in summary.items():
        print(f"  {code}:")
        for plat, info in plats.items():
            print(f"    {plat}: {info}")
