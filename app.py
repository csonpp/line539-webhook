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

# LINE SDK
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, JoinEvent

# Google Drive
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow

app = Flask(__name__)

# ====== 環境變數設定 ======
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET       = os.getenv("LINE_CHANNEL_SECRET")
if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise RuntimeError("請設定環境變數 LINE_CHANNEL_ACCESS_TOKEN 與 LINE_CHANNEL_SECRET")

SCOPES = ['https://www.googleapis.com/auth/drive.file']
# Google service account JSON 或 OAuth credentials
# 1) GOOGLE_SERVICE_ACCOUNT_JSON
# 2) GOOGLE_APPLICATION_CREDENTIALS
# 3) credentials.json + token.pickle (OAuth flow)

# =============================

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler       = WebhookHandler(LINE_CHANNEL_SECRET)

# ---- 初始化 Google Drive Client ----
credentials = None

# 1) 服務帳號 JSON
sa_json = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
if sa_json:
    try:
        info = json.loads(sa_json)
        credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception as e:
        print(f"⚠️ SERVICE_ACCOUNT_JSON 解析錯誤：{e}")

# 2) GOOGLE_APPLICATION_CREDENTIALS 檔案
if not credentials:
    path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '')
    if path and os.path.exists(path):
        try:
            credentials = service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
        except Exception as e:
            print(f"⚠️ 讀取 {path} 失敗：{e}")

# 3) credentials.json 當 Service Account
if not credentials and os.path.exists('credentials.json'):
    try:
        credentials = service_account.Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    except Exception as e:
        print(f"⚠️ credentials.json 當 Service Account 失敗：{e}")

# 4) OAuth client flow fallback
if not credentials and os.path.exists('credentials.json'):
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as f:
            pickle.dump(creds, f)
    credentials = creds

if credentials:
    drive_service = build('drive', 'v3', credentials=credentials)
else:
    print("⚠️ 無法取得 Drive 憑證，上傳功能將被略過")
    drive_service = None


def upload_and_get_link(filename: str) -> str:
    if not drive_service:
        return ""
    meta  = {'name': filename}
    media = MediaFileUpload(filename, mimetype='text/plain')
    f = drive_service.files().create(body=meta, media_body=media, fields='id').execute()
    fid = f.get('id')
    drive_service.permissions().create(
        fileId=fid,
        body={'role': 'reader', 'type': 'anyone'}
    ).execute()
    return f"https://drive.google.com/file/d/{fid}/view?usp=sharing"


def fetch_and_save_draws(fn="lottery_history.txt") -> bool:
    url = "https://www.pilio.idv.tw/lto539/list.asp"
    try:
        r = requests.get(url, timeout=10)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
    except:
        return False
    lines = []
    for tr in soup.select("table tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) < 2: continue
        date = tds[0].get_text(strip=True).split()[0].replace("/", "-")[:10]
        try:
            # 跳過星期日
            if datetime.strptime(date, "%Y-%m-%d").weekday() == 6:
                continue
        except:
            continue
        nums = list(map(int, re.findall(r"\d+", tds[1].get_text())))
        if len(nums) == 5:
            lines.append(f"{date} 開獎號碼：" + ", ".join(f"{n:02}" for n in nums))

    if not lines:
        return False
    with open(fn, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return True


def append_missing_draws(fn="lottery_history.txt"):
    existing = set()
    if os.path.exists(fn):
        for l in open(fn, encoding="utf-8"):
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
        date = tds[0].get_text(strip=True).split()[0].replace("/", "-")[:10]
        try:
            if datetime.strptime(date, "%Y-%m-%d").weekday() == 6:
                continue
        except:
            continue
        if date in existing:
            continue
        nums = list(map(int, re.findall(r"\d+", tds[1].get_text())))
        if len(nums) == 5:
            new.append(f"{date} 開獎號碼：" + ", ".join(f"{n:02}" for n in nums))
    if not new:
        return
    old = open(fn, encoding="utf-8").read()
    with open(fn, "w", encoding="utf-8") as f:
        f.write("\n".join(reversed(new)) + "\n" + old)


def get_last_n_dates(n=2):
    today = datetime.today()
    out, d = [], 1
    while len(out) < n:
        dt = today - timedelta(days=d)
        if dt.weekday() != 6:
            out.append(dt)
        d += 1
    return sorted(out)


def ensure_two_local(fn="lottery_history.txt"):
    if not os.path.exists(fn):
        open(fn, "w", encoding="utf-8").close()
    lines = [l for l in open(fn, encoding="utf-8") if re.match(r"\d{4}-\d{2}-\d{2} 開獎號碼", l)]
    if len(lines) >= 2:
        return
    for dt in get_last_n_dates(2):
        raw = input(f"請輸入 {dt:%Y-%m-%d} 開獎號碼（5 個）：")
        nums = re.findall(r"\d+", raw)
        if len(nums) == 5:
            with open(fn, "a", encoding="utf-8") as fw:
                fw.write(f"{dt:%Y-%m-%d} 開獎號碼：" + ", ".join(nums) + "\n")


def read_latest_2_draws(fn="lottery_history.txt"):
    rec = []
    for l in open(fn, encoding="utf-8"):
        m = re.match(r"(\d{4}-\d{2}-\d{2}) 開獎號碼：(.+)", l.strip())
        if m:
            dt = datetime.strptime(m.group(1), "%Y-%m-%d")
            nums = list(map(int, re.findall(r"\d+", m.group(2))))
            if len(nums) == 5:
                rec.append((dt, l.strip(), nums))
    rec.sort(key=lambda x: x[0])
    last_two = rec[-2:]
    texts = [r[1] for r in last_two]
    nums  = sorted({x for r in last_two for x in r[2]})
    return texts, nums


def group_numbers(cg):
    rem = sorted(set(range(1, 40)) - set(cg))
    A   = rem[:14]
    B   = rem[14:28]
    overflow = rem[28:]
    C   = sorted(cg + overflow)
    return A, B, C


def write_groups(A, B, C, today_draw=None):
    fn = "group_result.txt"
    texts, _ = read_latest_2_draws()
    with open(fn, "w", encoding="utf-8") as f:
        f.write("最近兩期開獎紀錄：\n" + "\n".join(texts) + "\n\n")
        f.write(f"A 組：{','.join(f'{x:02}' for x in A)}\n")
        f.write(f"B 組：{','.join(f'{x:02}' for x in B)}\n")
        f.write(f"C 組：{','.join(f'{x:02}' for x in C)}\n\n")
        f.write(f"產生於 {datetime.today():%Y-%m-%d}\n")
        if today_draw:
            hits = sorted(set(A + B + C) & set(today_draw))
            f.write(f"本期號碼：{','.join(f'{x:02}' for x in today_draw)} 中獎：{','.join(f'{x:02}' for x in hits)}\n")
    return fn


def process_report() -> str:
    hist = "lottery_history.txt"
    if not os.path.exists(hist) or os.path.getsize(hist) == 0:
        ok = fetch_and_save_draws(hist)
        if not ok:
            return ""  # 失敗
    else:
        append_missing_draws(hist)

    ensure_two_local(hist)
    # 不做互動式輸入 today_draw
    texts, nums = read_latest_2_draws(hist)
    A, B, C = group_numbers(nums)
    report_file = write_groups(A, B, C)
    return upload_and_get_link(report_file)


# ===== LINE Webhook =====
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
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
        link = process_report()
        if link:
            msg = f"今彩539下注報表已完成：\n{link}"
        else:
            msg = "❌ 報表產生失敗，請稍後再試。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
    elif "對獎" in txt:
        # 可同樣呼叫 lotto-line 邏輯
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="功能待實作"))
    else:
        # 回顯
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=txt))


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
