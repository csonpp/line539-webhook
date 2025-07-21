import os
import re
import json
import pickle
import requests
import smtplib
from datetime import datetime, timedelta
from flask import Flask, request, abort
from bs4 import BeautifulSoup
from email.message import EmailMessage
from dotenv import load_dotenv

# LINE SDK
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, JoinEvent

# Google Drive
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow

# 先載入 .env 裡的環境變數（如果有）
load_dotenv()

app = Flask(__name__)

# ====== 環境變數設定 ======
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET       = os.getenv("LINE_CHANNEL_SECRET")
if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise RuntimeError("請設定環境變數 LINE_CHANNEL_ACCESS_TOKEN 與 LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler       = WebhookHandler(LINE_CHANNEL_SECRET)

SCOPES = ['https://www.googleapis.com/auth/drive.file']

# 健康檢查路由 (避免 404)
@app.route("/", methods=["GET", "HEAD"])
def health_check():
    return "OK", 200

# Base dir for file operations
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- 初始化 Google Drive Client ----
credentials = None

# 嘗試用 GOOGLE_APPLICATION_CREDENTIALS 指向的檔案
cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
if cred_path and os.path.exists(cred_path):
    try:
        credentials = service_account.Credentials.from_service_account_file(
            cred_path, scopes=SCOPES
        )
    except Exception as e:
        print("⚠️ 讀取 GOOGLE_APPLICATION_CREDENTIALS 失敗：", e)

if not credentials:
    print("⚠️ 無法取得 Drive 憑證，上傳功能將被略過")
    drive_service = None
else:
    drive_service = build('drive', 'v3', credentials=credentials)


def upload_and_get_link(filename: str) -> str:
    """上傳檔案到 Google Drive 並回傳分享連結"""
    if not drive_service:
        return ""
    meta = {'name': os.path.basename(filename)}
    media = MediaFileUpload(filename, mimetype='text/plain')
    f = drive_service.files().create(
        body=meta, media_body=media, fields='id'
    ).execute()
    fid = f.get('id')
    drive_service.permissions().create(
        fileId=fid, body={'role': 'reader', 'type': 'anyone'}
    ).execute()
    return f"https://drive.google.com/file/d/{fid}/view?usp=sharing"


def fetch_and_save_draws(fn: str) -> bool:
    """抓今彩539號碼，寫入 fn"""
    url = "https://www.pilio.idv.tw/lto539/list.asp"
    try:
        r = requests.get(url, timeout=10)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print("❌ fetch_and_save_draws 連線失敗：", e)
        return False

    lines = []
    for tr in soup.select("table tr")[1:]:
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
        print("❌ fetch_and_save_draws: 無資料")
        return False

    with open(fn, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ fetch_and_save_draws: 已寫入 {len(lines)} 筆到 {fn}")
    return True


def append_missing_draws(fn: str):
    """補上遺漏的號碼到 fn 頂端"""
    existing = set()
    if os.path.exists(fn):
        with open(fn, encoding="utf-8") as f:
            for l in f:
                if re.match(r"\d{4}-\d{2}-\d{2}", l):
                    existing.add(l[:10])

    try:
        r = requests.get("https://www.pilio.idv.tw/lto539/list.asp", timeout=10)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
    except:
        return

    new = []
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
            new.append(f"{date_str} 開獎號碼：" + ", ".join(f"{n:02}" for n in nums))

    if not new:
        print("ℹ️ append_missing_draws: 無新資料")
        return

    old = open(fn, encoding="utf-8").read()
    with open(fn, "w", encoding="utf-8") as f:
        f.write("\n".join(reversed(new)) + "\n" + old)
    print(f"✅ append_missing_draws: 已補上 {len(new)} 筆")


def read_latest_2_draws(fn: str):
    """
    讀前兩期：回傳
      txts: ['2025-07-17 開獎號碼：01,02,…', '2025-07-16 開獎號碼：…']
      all_nums: [1,2,3,…]  # 合併後不重複之整數列表
    """
    rec = []
    with open(fn, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"(\d{4}-\d{2}-\d{2}) 開獎號碼：(.+)", line.strip())
            if not m:
                continue
            dt = datetime.strptime(m.group(1), "%Y-%m-%d")
            nums = list(map(int, re.findall(r"\d+", m.group(2))))
            if len(nums) == 5:
                rec.append((dt, nums))

    if len(rec) < 2:
        raise ValueError("歷史不足兩期")

    rec.sort(key=lambda x: x[0])
    last_two = rec[-2:]
    txts = [
        f"{d:%Y-%m-%d} 開獎號碼：" + ", ".join(f"{n:02}" for n in ns)
        for d, ns in last_two
    ]
    all_nums = sorted({n for _, ns in last_two for n in ns})
    return txts, all_nums


def group_numbers(cg):
    rem = sorted(set(range(1, 40)) - set(cg))
    A   = rem[:14]
    B   = rem[14:28]
    overflow = rem[28:]
    C   = sorted(cg + overflow)
    return A, B, C


def write_groups(A, B, C):
    fn = os.path.join(BASE_DIR, "group_result.txt")
    txts, _ = read_latest_2_draws(os.path.join(BASE_DIR, "lottery_history.txt"))
    with open(fn, "w", encoding="utf-8") as f:
        f.write("最近兩期開獎紀錄：\n" + "\n".join(txts) + "\n\n")
        f.write(f"A 組：{','.join(f'{x:02}' for x in A)}\n")
        f.write(f"B 組：{','.join(f'{x:02}' for x in B)}\n")
        f.write(f"C 組：{','.join(f'{x:02}' for x in C)}\n\n")
        f.write(f"產生於 {datetime.today():%Y-%m-%d}\n")
    return fn


def process_report() -> str:
    hist = os.path.join(BASE_DIR, "lottery_history.txt")
    if not fetch_and_save_draws(hist):
        return ""
    append_missing_draws(hist)

    try:
        txts, nums = read_latest_2_draws(hist)
    except Exception as e:
        print("❌ read_latest_2_draws 錯誤：", e)
        return ""

    try:
        A, B, C = group_numbers(nums)
        report_file = write_groups(A, B, C)
    except Exception as e:
        print("❌ 寫入報表錯誤：", e)
        return ""

    link = upload_and_get_link(report_file)
    print("🔗 已上傳並取得分享連結：", link)
    return link or ""


# ===== LINE Webhook =====
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body      = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(JoinEvent)
def on_join(event):
    gid = event.source.group_id or event.source.user_id
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"已加入，群組/用戶ID：{gid}")
    )


@handler.add(MessageEvent, message=TextMessage)
def on_message(event):
    txt = event.message.text.strip()
    if "注單" in txt:
        print(">>> 收到 注單 指令，開始產報表")
        try:
            link = process_report()
        except Exception as e:
            print("❌ process_report 未捕捉的例外：", e)
            link = ""
        if link:
            reply = f"今彩539下注報表已完成：\n{link}"
        else:
            reply = "❌ 報表產生失敗，請稍後再試。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    else:
        # 其他訊息原樣回覆
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=txt))


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
