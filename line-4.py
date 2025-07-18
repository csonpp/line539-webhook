import os
import re
import sys
import smtplib
import requests
from datetime import datetime, timedelta
from copy import deepcopy
from bs4 import BeautifulSoup
from email.message import EmailMessage

# Google Drive（只需要這幾個）
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
import pickle
import json

# ====== 設定區 ======
SERVICE_ACCOUNT_FILE = "credentials.json"  # 用 OAuth 下載的 credentials.json
SCOPES = ['https://www.googleapis.com/auth/drive.file']

LINE_CHANNEL_TOKEN = "UCWxMVzypOWSEB2qUaBF+kIzUtKQYAAAsvR5k1praIARx4K2gR7v3/FaSYG8k7K9LcRDdn1Pzf/okys0TN2V+U oHtwXKaZ4a21AZ8vzkjMwLtZTWHuR5RuHXtkltpFxP+t4D0NxxrpRV2l261spcXwdB04t89/1O/w1cDnyilFU="
LINE_USER_IDS = [
    "Ub8f9a069deae09a3694391a0bba53919",
    # 可再加第二、第三位 userId
]
# ==================

# ---- 驗證 credentials.json ----
try:
    with open(SERVICE_ACCOUNT_FILE, "r", encoding="utf-8") as tf:
        json.load(tf)
except FileNotFoundError:
    print(f"❌ 找不到 {SERVICE_ACCOUNT_FILE}，請放在腳本同一資料夾並命名正確")
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"❌ 無法解析 {SERVICE_ACCOUNT_FILE}，請重新下載 OAuth credentials 金鑰檔，錯誤：{e}")
    sys.exit(1)

# ★★★★★ 不要再 import 或使用 service_account 相關內容 ★★★★★

def upload_and_get_link(filename):
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    service = build('drive', 'v3', credentials=creds)
    file_metadata = {'name': filename}
    media = MediaFileUpload(filename, mimetype='text/plain')
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = file.get('id')
    # 設為公開可讀
    service.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
    share_link = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
    print(f"📤 已上傳 {filename} 並產生分享連結")
    return share_link

# ===============================
# 其餘功能原樣保留，不動
# ===============================

def fetch_and_save_draws(filename="lottery_history.txt"):
    url = "https://www.pilio.idv.tw/lto539/list.asp"
    try:
        resp = requests.get(url, timeout=10)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"❌ 無法連線到官網：{e}")
        return False
    rows = soup.select("table tr")[1:]
    lines = []
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 2: continue
        date_str = tds[0].get_text(strip=True).split()[0].replace("/", "-")[:10]
        try:
            if datetime.strptime(date_str, "%Y-%m-%d").weekday() == 6:
                continue
        except:
            continue
        nums = list(map(int, re.findall(r"\d+", tds[1].get_text())))
        if len(nums) == 5:
            lines.append(f"{date_str} 開獎號碼：" + ", ".join(f"{n:02}" for n in nums))
    if not lines:
        print("⚠️ 沒有抓到任何資料")
        return False
    with open(filename, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")
    print(f"✅ 已寫入 {len(lines)} 筆開獎資料到 {filename}")
    return True

def append_missing_draws(filename="lottery_history.txt"):
    existing = set()
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                if re.match(r"\d{4}-\d{2}-\d{2}", line):
                    existing.add(line[:10])
    try:
        resp = requests.get("https://www.pilio.idv.tw/lto539/list.asp", timeout=10)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"ℹ️ 無法連線到官網：{e}，保留本地紀錄")
        return
    new_lines = []
    for tr in soup.select("table tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) < 2: continue
        date_str = tds[0].get_text(strip=True).split()[0].replace("/", "-")[:10]
        try:
            if datetime.strptime(date_str, "%Y-%m-%d").weekday() == 6:
                continue
        except:
            continue
        if date_str in existing:
            continue
        nums = list(map(int, re.findall(r"\d+", tds[1].get_text())))
        if len(nums) == 5:
            new_lines.append(f"{date_str} 開獎號碼：" + ", ".join(f"{n:02}" for n in nums))
    if not new_lines:
        print("📄 沒有缺漏需要補上的資料")
        return
    with open(filename, "r", encoding="utf-8") as f:
        old = f.read()
    with open(filename, "w", encoding="utf-8") as f:
        for ln in reversed(new_lines):
            f.write(ln + "\n")
        f.write(old)
    print(f"✅ 已自動補上 {len(new_lines)} 筆資料（置頂顯示）")

def get_last_n_dates(n=2):
    today = datetime.today()
    res = []
    delta = 1
    while len(res) < n:
        dt = today - timedelta(days=delta)
        if dt.weekday() != 6:
            res.append(dt)
        delta += 1
    return sorted(res)

def ensure_two_local(filename="lottery_history.txt"):
    if not os.path.exists(filename):
        open(filename, "w", encoding="utf-8").close()
    with open(filename, "r", encoding="utf-8") as f:
        lines = [l for l in f if re.match(r"\d{4}-\d{2}-\d{2} 開獎號碼", l)]
    if len(lines) < 2:
        print("⚠️ 本地歷史不足兩期，請手動補齊：")
        for dt in get_last_n_dates(2):
            while True:
                raw = input(f"請輸入 {dt:%Y-%m-%d} 開獎號碼（5個）：")
                nums = list(map(int, re.findall(r"\d+", raw)))
                if len(nums) == 5 and all(1 <= x <= 39 for x in nums):
                    with open(filename, "a", encoding="utf-8") as f:
                        f.write(f"{dt:%Y-%m-%d} 開獎號碼：" +
                                ", ".join(f"{x:02}" for x in nums) + "\n")
                    break
                print("⚠️ 輸入錯誤，請再試。")

def check_and_append_today_draw(filename="lottery_history.txt"):
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    if now.weekday() == 6 or now.hour < 21:
        return None
    if os.path.exists(filename) and today in open(filename, "r", encoding="utf-8").read():
        return None
    while True:
        raw = input(f"已過21:00，請輸入今日（{today}）開獎號碼（5個）：")
        nums = list(map(int, re.findall(r"\d+", raw)))
        if len(nums) == 5 and all(1 <= x <= 39 for x in nums):
            with open(filename, "a", encoding="utf-8") as f:
                f.write(f"{today} 開獎號碼：" +
                        ", ".join(f"{x:02}" for x in nums) + "\n")
            return nums
        print("⚠️ 請輸入正確格式")

def read_latest_2_draws(filename="lottery_history.txt"):
    records = []
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"(\d{4}-\d{2}-\d{2}) 開獎號碼：(.+)", line.strip())
            if m:
                dt = datetime.strptime(m.group(1), "%Y-%m-%d")
                nums = list(map(int, re.findall(r"\d+", m.group(2))))
                if len(nums) == 5:
                    records.append((dt, line.strip(), nums))
    if len(records) < 2:
        raise ValueError("檔案中不足兩期資料")
    records.sort(key=lambda x: x[0])
    last_two = records[-2:]
    recent_lines = [r[1] for r in last_two]
    recent_nums = sorted({x for r in last_two for x in r[2]})
    return recent_lines, recent_nums, recent_lines[-1]

def group_numbers(c_group):
    all_nums = set(range(1, 40))
    rem = sorted(all_nums - set(c_group))
    A_range = list(range(1, 10)) + list(range(20, 30))
    B_range = list(range(10, 20)) + list(range(30, 40))
    A_full = [x for x in rem if x in A_range]
    B_full = [x for x in rem if x in B_range]
    A = A_full[:14]
    B = B_full[:14]
    overflow = A_full[14:] + B_full[14:]
    C = sorted(set(c_group + overflow))
    while len(A) < 14 and C:
        A.append(C.pop())
    while len(B) < 14 and C:
        B.append(C.pop())
    return sorted(A), sorted(B), sorted(C)

def write_combination_rows(title, p1, p2, file):
    rows = [p1[:7], p1[7:], p2[:7], p2[7:]]
    file.write(f"{title}（共 {len(p1)+len(p2)} 個號碼）：\n")
    labels = [f"#{i}".rjust(4) for i in range(1, 8)]
    file.write("位置：" + "".join(labels) + "\n")
    for r in rows:
        file.write("       " + "".join(f"{x:02}".rjust(4) for x in r) + "\n")
    file.write("\n")

def save_groups_and_bets(A, B, C, today_draw=None,
                        filename="group_result.txt", recent_lines=None):
    AB, AC, BC = sorted(set(A+B)), sorted(set(A+C)), sorted(set(B+C))
    with open(filename, "w", encoding="utf-8") as f:
        if recent_lines:
            f.write("最近兩期開獎紀錄：\n")
            for ln in recent_lines:
                f.write(ln + "\n")
            f.write("\n")
        f.write("原始三組號碼：\n")
        f.write("A 組（最多14）：\n" + ", ".join(f"{x:02}" for x in A) + "\n")
        f.write("B 組（最多14）：\n" + ", ".join(f"{x:02}" for x in B) + "\n")
        f.write("C 組（含溢出/補足）：\n" + ", ".join(f"{x:02}" for x in C) + "\n\n")
        f.write(f"合併後下注排列（每排7個）－產生於 {datetime.today():%Y-%m-%d}\n\n")
        write_combination_rows("A + B", A, B, f)
        write_combination_rows("A + C", A, C, f)
        write_combination_rows("B + C", B, C, f)
        if today_draw:
            f.write("對獎結果：\n")
            f.write(f"👉 本期號碼：{sorted(f"{n:02}" for n in today_draw)}\n")
            for title, combo in [("A+B", AB), ("A+C", AC), ("B+C", BC)]:
                hits = set(combo) & set(today_draw)
                f.write(f"{title} 中獎：{sorted(f"{h:02}" for h in hits)} （{len(hits)}）\n")
            f.write("\n")

def backup_group_result():
    today = datetime.today().strftime("%Y-%m-%d")
    bak = f"group_result_{today}.txt"
    if os.path.exists("group_result.txt"):
        with open("group_result.txt", "r", encoding="utf-8") as s, \
             open(bak, "w", encoding="utf-8") as d:
            d.write(s.read())
        print(f"📁 已備份至 {bak}")

def send_email_report():
    msg = EmailMessage()
    msg["Subject"] = "今彩539下注報告"
    msg["From"]    = "twblackbox@gmail.com"   # 改成 Brevo 的 SMTP 用戶名
    msg["To"]      = "csonpp@gmail.com"
    msg.set_content("請查收 group_result.txt")
    with open("group_result.txt", "rb") as f:
        msg.add_attachment(f.read(), maintype="text",
                           subtype="plain", filename="group_result.txt")
    smtp_user = "908708004@smtp-brevo.com"
    smtp_pass = "Wx8670BtzIcnO9hm"   # ←請換成你最新的 API Key
    try:
        with smtplib.SMTP("smtp-relay.brevo.com", 587) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.send_message(msg)
        print("📧 Email 已發送")
    except Exception as e:
        print("❌ 發信失敗：", e)

def send_line_push(text):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}",
        "Content-Type": "application/json"
    }
    for uid in LINE_USER_IDS:
        payload = {"to": uid, "messages": [{"type": "text", "text": text}]}
        print("▶ 推播 payload:", payload)
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"📨 已成功推播給 {uid}")
        else:
            print(f"❌ 推播給 {uid} 失敗 ({resp.status_code}): {resp.text}")

def main():
    hist = "lottery_history.txt"
    # 1) 首次 or 空檔 → 全抓；否則增量補
    if not os.path.exists(hist) or os.path.getsize(hist) == 0:
        ok = fetch_and_save_draws(hist)
        if not ok:
            open(hist, "w", encoding="utf-8").close()
    else:
        append_missing_draws(hist)
    # 2) 補至少兩期
    ensure_two_local(hist)
    # 3) 補今日
    today_draw = check_and_append_today_draw(hist)
    # 4) 讀最近兩期、分組、排版、對獎、備份、通知
    recent, cg, _ = read_latest_2_draws(hist)
    A, B, C = group_numbers(cg)
    save_groups_and_bets(A, B, C, today_draw,
                        filename="group_result.txt",
                        recent_lines=recent)
    backup_group_result()
    send_email_report()
    # 5) 上傳 Drive 並取回公開連結
    share_link = upload_and_get_link("group_result.txt")
    print("🔗 Drive 分享連結：", share_link)
    # 6) LINE 推播檔案連結
    dt = datetime.today().strftime("%Y-%m-%d")
    send_line_push(f"今彩539下注報告已完成 ({dt})，點此下載報表：\n{share_link}")

if __name__ == "__main__":
    main()
