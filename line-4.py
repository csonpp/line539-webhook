# -*- coding: utf-8 -*-
# line-4.py  (下注報表產出 / 上傳 / 寄信 / LINE 推播)
# Updated: 2025-07-23

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
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow

# ====== 設定區 ======
SCOPES = ['https://www.googleapis.com/auth/drive.file']
DEBUG = os.getenv("DEBUG", "0") == "1"

# Google Drive 目標資料夾（已幫你放入固定值）
DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "13uLGaxqOe0FVX3utlvZbcpdpU0YNoKU7").strip()

# LINE
DEFAULT_LINE_CHANNEL_TOKEN = os.getenv("DEFAULT_LINE_CHANNEL_TOKEN", "")
_raw_token = os.getenv("LINE_CHANNEL_TOKEN", "").strip() or DEFAULT_LINE_CHANNEL_TOKEN
LINE_CHANNEL_TOKEN = "".join(ch for ch in _raw_token if ord(ch) < 128)
LINE_USER_IDS = [uid.strip() for uid in os.getenv("LINE_USER_ID", "Ub8f9a069deae09a3694391a0bba53919").split(",") if uid.strip()]

# Email（Brevo / 其他 SMTP）
SMTP_HOST = os.getenv("SMTP_HOST", "smtp-relay.brevo.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
MAIL_FROM = os.getenv("MAIL_FROM", "twblackbox@gmail.com")
MAIL_TO   = os.getenv("MAIL_TO",   "csonpp@gmail.com")

# 檔名
HISTORY_FILE = "lottery_history.txt"
GROUP_FILE   = "group_result.txt"


# =====================================================
# Google Drive helpers
# =====================================================
def _load_service_account_json():
    raw = (
        os.getenv("SERVICE_ACCOUNT_JSON", "").strip()
        or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    )
    if not raw and os.path.exists("credentials.json"):
        try:
            raw = open("credentials.json", "r", encoding="utf-8").read()
        except Exception:
            pass
    if not raw:
        return None

    if not raw.startswith("{"):
        # 可能是 base64
        try:
            import base64
            raw = base64.b64decode(raw).decode("utf-8")
        except Exception:
            pass
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"⚠️ SERVICE_ACCOUNT_JSON 解析錯誤：{e}")
        return None


def build_drive_service():
    # 1) Service Account JSON
    info = _load_service_account_json()
    if info:
        need = {"type", "private_key", "client_email", "token_uri"}
        miss = need - set(info.keys())
        if miss:
            print(f"⚠️ Service Account JSON 缺欄位：{miss}")
        else:
            try:
                creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
                return build('drive', 'v3', credentials=creds)
            except Exception as e:
                print(f"⚠️ 以 Service Account info 建立 Drive 失敗：{e}")

    # 2) GOOGLE_APPLICATION_CREDENTIALS
    key_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if key_path and os.path.exists(key_path):
        try:
            creds = service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
            return build('drive', 'v3', credentials=creds)
        except Exception as e:
            print(f"⚠️ 從 {key_path} 讀取 SA 憑證失敗：{e}")

    # 3) credentials.json -> SA
    if os.path.exists('credentials.json'):
        try:
            creds = service_account.Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
            return build('drive', 'v3', credentials=creds)
        except Exception as e:
            print(f"⚠️ 以 Service Account 讀取 credentials.json 失敗：{e}")

    # 4) OAuth Flow（本地可用，不建議 Render）
    if os.path.exists('credentials.json'):
        creds = None
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token_file:
                creds = pickle.load(token_file)
        if not creds or not creds.valid:
            try:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
                with open('token.pickle', 'wb') as token_file:
                    pickle.dump(creds, token_file)
            except Exception as e:
                print(f"⚠️ OAuth 流程失敗：{e}")
                creds = None
        if creds:
            return build('drive', 'v3', credentials=creds)

    print("⚠️ 找不到任何 Google Drive 憑證，後續上傳將略過")
    return None


drive_service = build_drive_service()


def upload_and_get_link(filename: str, folder_id: str = DRIVE_FOLDER_ID) -> str:
    """上傳檔案到指定資料夾並回傳公開分享連結。失敗回空字串。"""
    if not drive_service:
        print("⚠️ 跳過 upload_and_get_link，因為找不到憑證")
        return ""

    meta = {'name': os.path.basename(filename)}
    if folder_id:
        meta['parents'] = [folder_id]

    media = MediaFileUpload(filename, mimetype='text/plain')

    try:
        file = drive_service.files().create(
            body=meta,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
    except HttpError as e:
        if e.resp.status == 403 and 'storageQuotaExceeded' in str(e):
            print("❌ 403：Service Account 沒配額，請確認資料夾已共享給 SA 或改用 OAuth。")
            return ""
        print("❌ 上傳發生 HttpError：", e)
        return ""
    except Exception as e:
        print("❌ 上傳發生例外：", e)
        return ""

    file_id = file.get('id')
    try:
        drive_service.permissions().create(
            fileId=file_id,
            body={'role': 'reader', 'type': 'anyone'},
            supportsAllDrives=True
        ).execute()
    except Exception as e:
        print("⚠️ 設定公開權限失敗：", e)

    link = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
    print(f"📤 已上傳 {filename} 並產生分享連結：{link}")
    return link


# =====================================================
# 資料抓取 / 整理
# =====================================================
def fetch_and_save_draws(filename: str = HISTORY_FILE) -> bool:
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
            if datetime.strptime(date_str, "%Y-%m-%d").weekday() == 6:  # 跳過星期日
                continue
        except Exception:
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


def append_missing_draws(filename: str = HISTORY_FILE):
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
        except Exception:
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


def ensure_two_local(filename: str = HISTORY_FILE):
    if not os.path.exists(filename):
        open(filename, "w", encoding="utf-8").close()

    with open(filename, "r", encoding="utf-8") as f:
        lines = [l for l in f if re.match(r"\d{4}-\d{2}-\d{2} 開獎號碼", l)]

    if len(lines) < 2:
        print("⚠️ 本地歷史不足兩期，請手動補齊（本程式已移除互動輸入）")


def check_and_append_today_draw(filename: str = HISTORY_FILE):
    # Render/自動模式下不互動輸入，直接略過
    return None


def read_latest_2_draws(filename: str = HISTORY_FILE):
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
    return recent_lines, recent_nums, last_two[-1][1]


# =====================================================
# 分組/下注排列 & 輸出
# =====================================================
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


def save_groups_and_bets(A, B, C, today_draw=None, filename: str = GROUP_FILE, recent_lines=None):
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
        f.write(f"合併後下注排列（每排7個號碼）－產生於 {datetime.today():%Y-%m-%d}\n\n")
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
    if os.path.exists(GROUP_FILE):
        with open(GROUP_FILE, "r", encoding="utf-8") as s, open(bak, "w", encoding="utf-8") as d:
            d.write(s.read())
        print(f"📁 已備份至 {bak}")


# =====================================================
# Email & LINE
# =====================================================
def send_email_report():
    if not (SMTP_USER and SMTP_PASS and MAIL_TO):
        print("⚠️ Email 資訊不完整，略過寄信")
        return
    msg = EmailMessage()
    msg["Subject"] = "今彩539下注報告"
    msg["From"] = MAIL_FROM
    msg["To"] = MAIL_TO
    msg.set_content("請查收 group_result.txt")
    try:
        with open(GROUP_FILE, "rb") as f:
            msg.add_attachment(f.read(), maintype="text", subtype="plain", filename=GROUP_FILE)
    except Exception as e:
        print("⚠️ 無法附加 group_result.txt：", e)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        print("📧 Email 已發送")
    except Exception as e:
        print("❌ 發信失敗：", e)


def send_line_push(text: str):
    if not (LINE_CHANNEL_TOKEN and LINE_USER_IDS):
        print("⚠️ LINE_CHANNEL_TOKEN 或 USER_IDS 缺失，跳過推播")
        return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_TOKEN}", "Content-Type": "application/json"}
    for uid in LINE_USER_IDS:
        payload = {"to": uid, "messages": [{"type": "text", "text": text}]}
        if DEBUG:
            print("→ LINE Push payload:", payload)
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            if DEBUG:
                print(f"→ LINE Push status: {resp.status_code}, body: {resp.text}")
            if resp.status_code == 200:
                print(f"📨 已成功推播給 {uid}")
            else:
                print(f"❌ 推播給 {uid} 失敗：{resp.text}")
        except Exception as e:
            print("❌ LINE Push 時發生例外：", e)


# =====================================================
# main
# =====================================================
def main():
    # 1. 抓資料
    if not os.path.exists(HISTORY_FILE) or os.path.getsize(HISTORY_FILE) == 0:
        ok = fetch_and_save_draws(HISTORY_FILE)
        if not ok:
            open(HISTORY_FILE, "w", encoding="utf-8").close()
    else:
        append_missing_draws(HISTORY_FILE)

    # 2. 最近兩期
    recent_lines, c_group_source, _ = read_latest_2_draws(HISTORY_FILE)

    # 3. 分組
    A, B, C = group_numbers(c_group_source)

    # 4. 今日號碼（自動模式不輸入）
    today_draw = None

    # 5. 輸出下注結果
    save_groups_and_bets(A, B, C, today_draw, filename=GROUP_FILE, recent_lines=recent_lines)

    # 6. 備份
    backup_group_result()

    # 7. 寄信
    send_email_report()

    # 8. 上傳
    share_link = upload_and_get_link(GROUP_FILE)
    print("🔗 Drive 分享連結：", share_link)

    # 9. 推播
    dt = datetime.today().strftime("%Y-%m-%d")
    push_text = f"今彩539下注報告已完成 ({dt})，點此下載報表：\n{share_link}".rstrip()
    send_line_push(push_text)


if __name__ == "__main__":
    main()
