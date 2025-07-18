import os
import re
import sys
import time
import requests
from bs4 import BeautifulSoup
from math import comb
from datetime import datetime, timedelta

# ==== 可選 Drive 驗證 (此腳本暫不使用 Drive，上傳功能預留) ====
skip_drive = False
SERVICE_ACCOUNT_FILE = "credentials.json"
try:
    import json
    with open(SERVICE_ACCOUNT_FILE, 'r', encoding='utf-8') as tf:
        json.load(tf)
except Exception as e:
    print(f"⚠️ 無法讀取 {SERVICE_ACCOUNT_FILE}，Drive 功能將被略過：{e}")
    skip_drive = True

# ===== 設定 =====
LINE_CHANNEL_TOKEN = os.getenv("LINE_CHANNEL_TOKEN", "UCWxMVzypOWSEB2qUaBF+kIzUtKQYAAAsvR5k1praIARx4K2gR7v3/FaSYG8k7K9LcRDdn1Pzf/okys0TN2V+UoHtwXKaZ4a21AZ8vzkjMwLtZTWHuR5RuHXtkltpFxP+t4D0NxxrpRV2l261spcXwdB04t89/1O/w1cDnyilFU=")
LINE_USER_IDS = [
    os.getenv("LINE_USER_ID", "Ub8f9a069deae09a3694391a0bba53919"),
]
# ====================

def fetch_and_save_draws(filename="lottery_line.txt", retry=3):
    url = "https://www.pilio.idv.tw/lto539/list.asp"
    for attempt in range(retry):
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.encoding = 'utf-8'
            soup = BeautifulSoup(resp.text, 'html.parser')
            break
        except Exception as e:
            print(f"❌ 第{attempt+1}次連線失敗：{e}")
            if attempt < retry - 1:
                print("5秒後重試...")
                time.sleep(5)
            else:
                print("已超過重試次數，放棄抓取。")
                return None
    rows = soup.select("table tr")[1:]
    results = []
    for tr in rows:
        tds = tr.find_all('td')
        if len(tds) >= 2:
            date_str = tds[0].get_text(strip=True).split()[0].replace('/', '-')
            nums = list(map(int, re.findall(r"\d+", tds[1].get_text())))
            if len(nums) == 5:
                line = f"{date_str} 開獎號碼：" + ", ".join(f"{n:02}" for n in nums)
                results.append(line)
    if results:
        with open(filename, 'w', encoding='utf-8') as f:
            for l in results:
                f.write(l + "\n")
        print(f"✅ 已寫入 {len(results)} 筆開獎資料到 {filename}")
        return results[0]
    else:
        print("⚠️ 無開獎資料可寫入。")
        return None

def send_line_bot_push(token, to_id, msg):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {"to": to_id, "messages": [{"type":"text","text":msg}]}
    resp = requests.post(url, headers=headers, json=payload)
    print(f"推播 {to_id} 狀態：{resp.status_code}")
    return resp.status_code

def parse_group_result_file(filename="group_result.txt"):
    with open(filename, encoding='utf-8') as f:
        data = f.read()
    sets = {}
    for name in ['A + B', 'A + C', 'B + C']:
        pat = rf"{re.escape(name)}（.*?）：\n((?:.+\n)+?)(?=\n|$)"
        m = re.search(pat, data)
        if not m: continue
        lines = m.group(1).strip().split('\n')
        rows = [list(map(int, re.findall(r"\d+", line))) for line in lines if '位置' not in line]
        pillars = [[row[i] for row in rows if len(row)>i] for i in range(7)]
        sets[name] = pillars
    return sets

def check_group_winning(open_nums, group_set):
    pillar_hits = [sum(1 for n in open_nums if n in pillar) for pillar in group_set]
    hit_pillars = sum(1 for h in pillar_hits if h>0)
    total_hits = sum(pillar_hits)
    return hit_pillars, total_hits, pillar_hits

def calc_hits(hit_pillars, total_hits, pillar_hits):
    if hit_pillars<3 or total_hits<3: return 0
    if hit_pillars==3 and total_hits==3: return 1
    if hit_pillars==3 and total_hits==4: return 2
    if hit_pillars==4 and total_hits==4: return 4
    if hit_pillars==4 and total_hits==5: return 7
    if hit_pillars==5 and total_hits==5: return 10
    if hit_pillars==3 and total_hits==5:
        if 3 in pillar_hits: return 3
        if pillar_hits.count(2)==2: return 4
        return 3
    return comb(total_hits,3) if total_hits>=3 else 0

def make_lottery_report(open_nums, group_sets):
    total = 0
    lines = [f"開獎號碼：{' '.join(f'{n:02}' for n in open_nums)}"]
    for name, set_ in group_sets.items():
        hp, th, ph = check_group_winning(open_nums, set_)
        if hp>=3:
            detail = '、'.join(f"第{i+1}柱{ph[i]}個({','.join(str(n) for n in set_[i] if n in open_nums)})" for i in range(7) if ph[i]>0)
            hits = calc_hits(hp,th,ph)
            total += hits
            lines.append(f"{name}：中{hp}柱，共{th}號碼，{detail}，中{hits}碰")
        else:
            lines.append(f"{name}：未中獎，0碰")
    lines.append(f"本期共中{total}碰")
    return '\n'.join(lines)

if __name__ == '__main__':
    latest = fetch_and_save_draws()
    if latest:
        group_sets = parse_group_result_file()
        nums = list(map(int, re.findall(r"開獎號碼：([\d ,]+)", latest)[0].replace(',', ' ').split()))
        report = make_lottery_report(nums, group_sets)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        msg = f"{latest}\n{report}\n推播時間：{now}"
        print(msg)
        for uid in LINE_USER_IDS:
            send_line_bot_push(LINE_CHANNEL_TOKEN, uid, msg)
    else:
        print("無法取得開獎號碼，停止推播。")
