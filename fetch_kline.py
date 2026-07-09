#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集中际旭创(300308)日线数据，保存为 JSON 与 CSV。"""
import urllib.request
import urllib.parse
import json
import csv
import os

SEC_ID = "0.300308"          # 0=深交所, 300308=中际旭创
BEG = "20220101"
END = "20261231"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
BASE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

def fetch():
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": FIELDS2,
        "ut": "fa5fd1943c7b386f172d75920700205",
        "klt": "101",          # 101=日线
        "fqt": "1",            # 1=前复权
        "secid": SEC_ID,
        "beg": BEG,
        "end": END,
        "_": "1",
    }
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data

def parse(data):
    klines = data.get("data", {}).get("klines", [])
    name = data.get("data", {}).get("name", "")
    code = data.get("data", {}).get("code", "")
    rows = []
    for kl in klines:
        parts = kl.split(",")
        # f51日期,f52开,f53收,f54高,f55低,f56量,f57额,f58振幅,f59涨跌幅,f60涨跌额,f61换手
        rows.append({
            "date": parts[0],
            "open": float(parts[1]),
            "close": float(parts[2]),
            "high": float(parts[3]),
            "low": float(parts[4]),
            "volume": float(parts[5]),
            "amount": float(parts[6]),
            "amplitude": float(parts[7]),
            "pct_change": float(parts[8]),
            "change": float(parts[9]),
            "turnover": float(parts[10]),
        })
    return name, code, rows

def main():
    data = fetch()
    name, code, rows = parse(data)
    print(f"标的: {name}({code})  共 {len(rows)} 条日线")
    if rows:
        print("区间:", rows[0]["date"], "->", rows[-1]["date"])
        print("首收:", rows[0]["close"], " 末收:", rows[-1]["close"])
    json_path = os.path.join(OUT_DIR, "kline_300308.json")
    csv_path = os.path.join(OUT_DIR, "kline_300308.csv")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"name": name, "code": code, "rows": rows}, f, ensure_ascii=False, indent=2)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date","open","close","high","low","volume","amount","amplitude","pct_change","change","turnover"])
        w.writeheader()
        w.writerows(rows)
    print("已保存:", json_path)
    print("已保存:", csv_path)

if __name__ == "__main__":
    main()
