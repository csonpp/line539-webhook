#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lotto-line.py
-------------------------------------------------
- 抓取開獎、對獎（幾碰），輸出報告
- 需要先有 group_result.txt（由 line-4.py 產出）
- 用 LINE Bot Push 推播結果
"""

import os
import re
import sys
import time
import json
import requests
import subprocess
from bs4 import BeautifulSoup
from math import comb
from datetime import datetime
from typing import Dict, List, Tuple

# LINE Bot
LINE_CHANNEL_TOKEN = (os.getenv("LINE_CHANNEL_TOKEN") or os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
LINE_CHANNEL_TOKEN = "".join(ch for ch in LINE_CHANNEL_TOKEN if ord(ch) < 128)
LINE_USER_IDS = [uid.strip() for uid in os.getenv("LINE_USER_ID", "Ub8f9a069deae09a3694391a0bba53919").split(",") if uid.strip()]
DEBUG = os.getenv("DEBUG", "0") == "1"

GROUP_FILE   = os.getenv("GROUP_FILE", "group_result.txt")
HISTORY_FILE = os.getenv("HISTORY_FILE", "lottery_history.txt")

# ---------------------
# 抓官網資料
# ---------------------
def fetch_and_save_draws(filename: str = HISTORY_FILE, retry: int = 3) -> str | None:
    url = "https://www.pilio.idv.tw/lto539/list.asp"
    soup = None
    for attempt in range(retry):
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.encoding = 'utf-8'
            soup = BeautifulSoup(resp.text, 'html.parser')
            break
        except Exception as e:
            print(f"❌ 第{attempt+1}次連線失敗：{e}")
            if attempt < retry - 1:
                time.sleep(5)
            else:
                return None

    rows = soup.select("table tr")[1:]
    results = []
    for tr in rows:
        tds = tr.find_all('td')
        if len(tds) >= 2:
            date_str = tds[0].get_text(strip=True).split()[0].replace('/', '-')
            nums = list(map(int, re.findall(r"\d+", tds[1].get_text())))
            if len(nums) == 5:
                results.append(f"{date_str} 開獎號碼：" + ", ".join(f"{n:02}" for n in nums))

    if results:
        with open(filename, 'w', encoding='utf-8') as f:
            for l in results:
                f.write(l + "\n")
        print(f"✅ 已寫入 {len(results)} 筆開獎資料到 {filename}")
        return results[0]
    else:
        print("⚠️ 無開獎資料可寫入。")
        return None

# ---------------------
# LINE 推播
# ---------------------
def send_line_bot_push(token: str, to_id: str, msg: str) -> int:
    if not token:
        print("⚠️ LINE_CHANNEL_TOKEN 未設定，略過推播")
        return -1
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"to": to_id, "messages": [{"type":"text","text":msg}]}
    if DEBUG:
        print("→ LINE Push payload:", payload)
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if DEBUG:
            print(f"→ LINE Push status: {resp.status_code}, body: {resp.text}")
        return resp.status_code
    except Exception as e:
        print("❌ LINE 推播發生例外：", e)
        return -1

# ---------------------
# 解析 group_result.txt
# ---------------------
def parse_group_result_file(filename: str = GROUP_FILE) -> Dict[str, List[List[int]]]:
    with open(filename, encoding='utf-8') as f:
        data = f.read()
    sets: Dict[str, List[List[int]]] = {}
    for name in ['A + B', 'A + C', 'B + C']:
        pat = rf"{re.escape(name)}（.*?）：\n((?:.+\n)+?)(?=\n|$)"
        m = re.search(pat, data, flags=re.DOTALL)
        if not m:
            continue
        block = m.group(1)
        lines = [ln for ln in block.strip().splitlines() if '位置' not in ln and ln.strip()]
        rows = [list(map(int, re.findall(r"\d+", line))) for line in lines]
        max_len = max(len(r) for r in rows)
        pillars = [[row[i] for row in rows if len(row) > i] for i in range(max_len)]
        sets[name] = pillars
    return sets

# ---------------------
# 中獎計算
# ---------------------
def check_group_winning(open_nums: List[int], group_set: List[List[int]]) -> Tuple[int, int, List[int]]:
    pillar_hits = [sum(1 for n in open_nums if n in pillar) for pillar in group_set]
    hit_pillars = sum(1 for h in pillar_hits if h > 0)
    total_hits  = sum(pillar_hits)
    return hit_pillars, total_hits, pillar_hits

def calc_hits(hit_pillars: int, total_hits: int, pillar_hits: List[int]) -> int:
    if hit_pillars < 3 or total_hits < 3:
        return 0
    if hit_pillars == 3 and total_hits == 3:
        return 1
    if hit_pillars == 3 and total_hits == 4:
        return 2
    if hit_pillars == 4 and total_hits == 4:
        return 4
    if hit_pillars == 4 and total_hits == 5:
        return 7
    if hit_pillars == 5 and total_hits == 5:
        return 10
    if hit_pillars == 3 and total_hits == 5:
        if 3 in pillar_hits:
            return 3
        if pillar_hits.count(2) == 2:
            return 4
        return 3
    return comb(total_hits, 3) if total_hits >= 3 else 0

def make_lottery_report(open_nums: List[int], group_sets: Dict[str, List[List[int]]]) -> str:
    total = 0
    lines = [f"開獎號碼：{' '.join(f'{n:02}' for n in open_nums)}"]
    for name, set_ in group_sets.items():
        hp, th, ph = check_group_winning(open_nums, set_)
        if hp >= 3:
            detail_parts = []
            for i, hits in enumerate(ph):
                if hits > 0:
                    hit_nums = [n for n in set_[i] if n in open_nums]
                    detail_parts.append(f"第{i+1}柱{hits}個({','.join(f'{n:02}' for n in hit_nums)})")
            detail = '、'.join(detail_parts)
            hits = calc_hits(hp, th, ph)
            total += hits
            lines.append(f"{name}：中{hp}柱，共{th}號碼，{detail}，中{hits}碰")
        else:
            lines.append(f"{name}：未中獎，0碰")
    lines.append(f"本期共中{total}碰")
    return "\n".join(lines)

# ---------------------
# 主流程
# ---------------------
if __name__ == '__main__':
    latest = fetch_and_save_draws()
    if not latest:
        print("無法取得開獎號碼，停止流程。")
        sys.exit(1)

    if not os.path.exists(GROUP_FILE):
        print(f"⚠️ 找不到 {GROUP_FILE}，先執行 line-4.py 生成下注排列")
        proc = subprocess.run([sys.executable, 'line-4.py'], cwd=os.getcwd(), capture_output=True, text=True)
        if DEBUG:
            print("line-4.py stdout:\n", proc.stdout)
            print("line-4.py stderr:\n", proc.stderr)
        if not os.path.exists(GROUP_FILE):
            print("❌ 執行 line-4.py 後仍找不到 group_result.txt，無法對獎")
            sys.exit(1)

    try:
        group_sets = parse_group_result_file(GROUP_FILE)
    except FileNotFoundError:
        print("❌ 找不到 group_result.txt，無法進行對獎")
        sys.exit(1)

    m = re.search(r"開獎號碼：([\\d ,]+)", latest)
    if not m:
        print("❌ 無法從最新行解析開獎號碼")
        sys.exit(1)
    open_nums = list(map(int, re.findall(r"\\d+", m.group(1))))

    report = make_lottery_report(open_nums, group_sets)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    msg = f"{latest}\n{report}\n推播時間：{now_str}"

    print(msg)
    for uid in LINE_USER_IDS:
        status = send_line_bot_push(LINE_CHANNEL_TOKEN, uid, msg)
        if status == 200:
            print(f"📨 已成功推播給 {uid}")
        else:
            print(f"❌ 推播給 {uid} 失敗 (status={status})")
