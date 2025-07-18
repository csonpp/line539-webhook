import os
import re
import smtplib
import requests
import pickle
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from email.message import EmailMessage

# Google Drive
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow

# ====== 設定區 ======
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# 如果你希望硬編碼在程式內，也可以在這裡設定：
DEFAULT_LINE_CHANNEL_TOKEN = "UCWxMVzypOWSEB2qUaBF+kIzUtKQYAAAsvR5k1praIARx4K2gR7v3/FaSYG8k7K9LcRDdn1Pzf/okys0TN2V+UoHtwXKaZ4a21AZ8vzkjMwLtZTWHuR5RuHXtkltpFxP+t4D0NxxrpRV2l261spcXwdB04t89/1O/w1cDnyilFU="

# 先從環境變數讀 LINE_CHANNEL_TOKEN，如果沒設就 fallback 到上面的預設值
_raw_token = os.getenv("LINE_CHANNEL_TOKEN", "").strip() or DEFAULT_LINE_CHANNEL_TOKEN
# 只保留 ASCII 字元
LINE_CHANNEL_TOKEN = "".join(ch for ch in _raw_token if ord(ch) < 128)

LINE_USER_IDS = [
    "Ub8f9a069deae09a3694391a0bba53919",
]
# ==================

# ---- 初始化 Google Drive client ----
credentials = None

# 1) 嘗試從環境變數 GOOGLE_SERVICE_ACCOUNT_JSON
sa_json = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
if sa_json:
    try:
        info = json.loads(sa_json)
        credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception as e:
        print(f"⚠️ GOOGLE_SERVICE_ACCOUNT_JSON 解析錯誤：{e}")

# 2) 嘗試從 GOOGLE_APPLICATION_CREDENTIALS 檔案路徑
if not credentials:
    key_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if key_path and os.path.exists(key_path):
        try:
            credentials = service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
        except Exception as e:
            print(f"⚠️ 從 {key_path} 讀取憑證失敗：{e}")

# 3) 嘗試把本地 credentials.json 當作 Service Account
if not credentials and os.path.exists('credentials.json'):
    try:
        credentials = service_account.Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    except Exception as e:
        print(f"⚠️ 以 Service Account 讀取 credentials.json 失敗：{e}")

# 4) 最後 fallback 到 OAuth client flow（如果 credentials.json 是 OAuth client）
if not credentials and os.path.exists('credentials.json'):
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token_file:
            creds = pickle.load(token_file)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token_file:
            pickle.dump(creds, token_file)
    credentials = creds

# 5) 建立 drive_service 或略過
if credentials:
    drive_service = build('drive', 'v3', credentials=credentials)
else:
    print("⚠️ 找不到任何 Google Drive 憑證，後續 upload_and_get_link 將被略過")
    drive_service = None


def upload_and_get_link(filename):
    """上傳檔案到 Google Drive 並回傳公開分享連結"""
    if not drive_service:
        print("⚠️ 跳過 upload_and_get_link，因為找不到憑證")
        return ""
    meta = {'name': filename}
    media = MediaFileUpload(filename, mimetype='text/plain')
    file = drive_service.files().create(body=meta, media_body=media, fields='id').execute()
    file_id = file.get('id')
    drive_service.permissions().create(
        fileId=file_id,
        body={'role': 'reader', 'type': 'anyone'}
    ).execute()
    link = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
    print(f"📤 已上傳 {filename} 並產生分享連結：{link}")
    return link


def fetch_and_save_draws(filename="lottery_history.txt"):
    url = "https://www.pilio.idv.tw/lto539/list.asp"
    try:
        r = requests.get(url, timeout=10)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"❌ 無法連線到官網：{e}")
        return False

    rows = soup.select("table tr")[1:]
    lines = []
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
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
        r = requests.get("https://www.pilio.idv.tw/lto539/list.asp", timeout=10)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"ℹ️ 無法連線到官網：{e}，保留本地紀錄")
        return

    new_lines = []
    for tr in soup.select("table tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
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

    old = open(filename, "r", encoding="utf-8").read()
    with open(filename, "w", encoding="utf-8") as f:
        for ln in reversed(new_lines):
            f.write(ln + "\n")
        f.write(old)
    print(f"✅ 已自動補上 {len(new_lines)} 筆資料（置頂顯示）")


def get_last_n_dates(n=2):
    today = datetime.today()
    res = []
    d = 1
    while len(res) < n:
        dt = today - timedelta(days=d)
        if dt.weekday() != 6:
            res.append(dt)
        d += 1
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
                raw = input(f"請輸入 {dt:%Y-%m-%d} 開獎號碼（5 個）：")
                nums = list(map(int, re.findall(r"\d+", raw)))
                if len(nums) == 5 and all(1 <= x <= 39 for x in nums):
                    with open(filename, "a", encoding="utf-8") as fw:
                        fw.write(f"{dt:%Y-%m-%d} 開獎號碼：" + ", ".join(f"{x:02}" for x in nums) + "\n")
                    break
                print("⚠️ 輸入錯誤，請再試。")


def check_and_append_today_draw(filename="lottery_history.txt"):
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    if now.weekday() == 6 or now.hour < 21:
        return None
    if today in open(filename, "r", encoding="utf-8").read():
        return None
    while True:
        raw = input(f"已過21:00，請輸入今日（{today}）開獎號碼（5 個）：")
        nums = list(map(int, re.findall(r"\d+", raw)))
        if len(nums) == 5 and all(1 <= x <= 39 for x in nums):
            with open(filename, "a", encoding="utf-8") as f:
                f.write(f"{today} 開獎號碼：" + ", ".join(f"{x:02}" for x in nums) + "\n")
            return nums
        print("⚠️ 輸入錯誤，請再試。")


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
    A, B = A_full[:14], B_full[:14]
    overflow = A_full[14:] + B_full[14:]
    C = sorted(set(c_group + overflow))
    while len(A) < 14 and C:
        A.append(C.pop())
    while len(B) < 14 and C:
        B.append(C.pop())
    return sorted(A), sorted(B), sorted(C)


def write_combination_rows(title, p1, p2, f):
    rows = [p1[:7], p1[7:], p2[:7], p2[7:]]
    f.write(f"{title}（共 {len(p1)+len(p2)} 個號碼）：\n")
    labels = [f"#{i}".rjust(4) for i in range(1, 8)]
    f.write("位置：" + "".join(labels) + "\n")
    for r in rows:
        f.write("       " + "".join(f"{x:02}".rjust(4) for x in r) + "\n")
    f.write("\n")


def save_groups_and_bets(A, B, C, today_draw=None, filename="group_result.txt", recent_lines=None):
    AB = sorted(set(A + B))
    AC = sorted(set(A + C))
    BC = sorted(set(B + C))
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
            f.write(f"👉 本期號碼：{sorted(today_draw)}\n")
            for title, combo in [("A+B", AB), ("A+C", AC), ("B+C", BC)]:
                hits = set(combo) & set(today_draw)
                f.write(f"{title} 中獎：{sorted(hits)} （{len(hits)}）\n")
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
    msg["From"] = "twblackbox@gmail.com"
    msg["To"] = "csonpp@gmail.com"
    msg.set_content("請查收 group_result.txt")
    with open("group_result.txt", "rb") as f:
        msg.add_attachment(f.read(), maintype="text", subtype="plain", filename="group_result.txt")
    smtp_user = "908708004@smtp-brevo.com"
    smtp_pass = "Wx8670BtzIcnO9hm"
    try:
        with smtplib.SMTP("smtp-relay.brevo.com", 587) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.send_message(msg)
        print("📧 Email 已發送")
    except Exception as e:
        print("❌ 發信失敗：", e)


def send_line_push(text):
    """對每個 LINE_USER_IDS 呼叫 push endpoint"""
    if not LINE_CHANNEL_TOKEN:
        print("⚠️ LINE_CHANNEL_TOKEN 讀不到，跳過推播")
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}",
        "Content-Type": "application/json"
    }

    for uid in LINE_USER_IDS:
        payload = {
            "to": uid,
            "messages": [{"type": "text", "text": text}]
        }
        print("→ LINE Push headers:", headers)
        print("→ LINE Push payload:", payload)
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            print(f"→ LINE Push status: {resp.status_code}, body: {resp.text}")
            if resp.status_code == 200:
                print(f"📨 已成功推播給 {uid}")
            else:
                print(f"❌ 推播給 {uid} 失敗，請確認 Channel Token / User ID 是否正確")
        except Exception as e:
            print("❌ LINE Push 時發生例外：", e)


def main():
    hist = "lottery_history.txt"
    if not os.path.exists(hist) or os.path.getsize(hist) == 0:
        ok = fetch_and_save_draws(hist)
        if not ok:
            open(hist, "w", encoding="utf-8").close()
    else:
        append_missing_draws(hist)

    ensure_two_local(hist)
    today_draw = check_and_append_today_draw(hist)
    recent, cg, _ = read_latest_2_draws(hist)
    A, B, C = group_numbers(cg)
    save_groups_and_bets(A, B, C, today_draw, filename="group_result.txt", recent_lines=recent)
    backup_group_result()
    send_email_report()
    share_link = upload_and_get_link("group_result.txt")
    print("🔗 Drive 分享連結：", share_link)
    dt = datetime.today().strftime("%Y-%m-%d")
    send_line_push(f"今彩539下注報告已完成 ({dt})，點此下載報表：\n{share_link}")


if __name__ == "__main__":
    main()
