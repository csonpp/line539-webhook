import requests
from bs4 import BeautifulSoup
import re
from math import comb

LINE_CHANNEL_TOKEN = "UCWxMVzypOWSEB2qUaBF+kIzUtKQYAAAsvR5k1praIARx4K2gR7v3/FaSYG8k7K9LcRDdn1Pzf/okys0TN2V+UoHtwXKaZ4a21AZ8vzkjMwLtZTWHuR5RuHXtkltpFxP+t4D0NxxrpRV2l261spcXwdB04t89/1O/w1cDnyilFU="
LINE_USER_IDS = [
    "Ub8f9a069deae09a3694391a0bba53919",
    # 可加入多個 user_id 或 group_id
]

def fetch_and_save_draws(filename="lottery_line.txt", retry=3): 
    url = "https://www.pilio.idv.tw/lto539/list.asp"
    for attempt in range(retry):
        try:
            response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            response.encoding = "utf-8"
            soup = BeautifulSoup(response.text, "html.parser")
            break
        except Exception as e:
            print(f"❌ 第{attempt+1}次連線失敗：{e}")
            if attempt < retry - 1:
                import time
                print("5秒後自動重試...")
                time.sleep(5)
            else:
                print("已超過重試次數，放棄。")
                return None
    rows = soup.select("table tr")[1:]
    results = []
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) >= 2:
            date_str = tds[0].get_text(strip=True).split()[0].replace("/", "-")
            try:
                draw_nums = list(map(int, re.findall(r"\d+", tds[1].get_text())))
                if len(draw_nums) == 5:
                    line = f"{date_str} 開獎號碼：" + ", ".join(f"{n:02}" for n in draw_nums)
                    results.append(line)
            except:
                continue
    if results:
        with open(filename, "w", encoding="utf-8") as f:
            for line in results:
                f.write(line + "\n")
        print(f"✅ 已成功寫入 {len(results)} 筆開獎資料到 {filename}")
        return results[0]
    else:
        print("⚠️ 沒有抓到任何資料")
        return None

def send_line_bot_push(channel_token, user_id, msg):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {channel_token}",
        "Content-Type": "application/json"
    }
    data = {
        "to": user_id,
        "messages": [{
            "type": "text",
            "text": msg
        }]
    }
    resp = requests.post(url, headers=headers, json=data)
    print(f"推播給 {user_id} 狀態：{resp.status_code}, 回應：{resp.text}")
    return resp.status_code

def parse_group_result_file(filename="group_result.txt"):
    with open(filename, encoding="utf-8") as f:
        content = f.read()
    sets = {}
    for set_name in ["A + B", "A + C", "B + C"]:
        pattern = rf"{re.escape(set_name)}（.*?\）：\n((?:.+\n)+?)(?=\n|$)"
        m = re.search(pattern, content)
        if not m:
            continue
        lines = m.group(1).strip().split("\n")
        number_rows = []
        for line in lines:
            # 跳過「位置」行、空行
            if "位置" in line or re.match(r"^\s*$", line):
                continue
            nums = list(map(int, re.findall(r"\d+", line)))
            if nums:
                number_rows.append(nums)
        # 橫排轉縱列（以縱列為柱）
        pillars = []
        for i in range(7):
            pillar = []
            for row in number_rows:
                if len(row) > i:
                    pillar.append(row[i])
            pillars.append(pillar)
        sets[set_name] = pillars
    return sets

def check_group_winning(open_nums, group_set):
    pillar_hits = [0] * 7
    for num in open_nums:
        for idx, pillar in enumerate(group_set):
            if num in pillar:
                pillar_hits[idx] += 1
                break  # 只計算一次
    hit_pillars = sum(1 for x in pillar_hits if x > 0)
    total_hits = sum(pillar_hits)  # 不會超過5
    return hit_pillars, total_hits, pillar_hits

def calc_hits(hit_pillars, total_hits, pillar_hits):
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
        elif pillar_hits.count(2) == 2:
            return 4
        else:
            return 3
    return comb(total_hits, 3) if total_hits >= 3 else 0

def make_lottery_report(open_nums, group_sets):
    lines = [f"開獎號碼：{' '.join(f'{n:02}' for n in open_nums)}"]
    total_碰 = 0
    for name, group in group_sets.items():
        hit_pillars, total_hits, pillar_hits = check_group_winning(open_nums, group)
        if hit_pillars >= 3:
            detail = "、".join(
                [f"第{i+1}柱{pillar_hits[i]}個" +
                 ("(" + "、".join(str(num) for num in group[i] if num in open_nums) + ")" if pillar_hits[i] else "")
                 for i in range(7) if pillar_hits[i]]
            )
            碰數 = calc_hits(hit_pillars, total_hits, pillar_hits)
            total_碰 += 碰數
            lines.append(f"{name}：中{hit_pillars}柱，共{total_hits}個號碼（{detail}），中{碰數}碰")
        else:
            lines.append(f"{name}：未中獎，中0碰")
    lines.append(f"本期合計共中{total_碰}碰")
    return "\n".join(lines)

if __name__ == "__main__":
    latest = fetch_and_save_draws()
    if latest:
        group_sets = parse_group_result_file("group_result.txt")
        open_nums = list(map(int, re.findall(r"開獎號碼：([\d ,]+)", latest)[0].replace(',', ' ').split()))
        report = make_lottery_report(open_nums, group_sets)
        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"{latest}\n{report}\n推播時間：{now_str}"
        print(msg)
        for user_id in LINE_USER_IDS:
            send_line_bot_push(LINE_CHANNEL_TOKEN, user_id, msg)
    else:
        print("未能獲取最新開獎資料，不進行推播。")
