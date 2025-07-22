# app.py
# ------------------------------
# Flask + LINE Bot + Google Drive (Render friendly)
# Updated: 2025-07-22
# ------------------------------

import os, re, sys, json, base64, threading, subprocess
from flask import Flask, request, abort

# optional: dotenv for local dev
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# LINE SDK
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# Google Drive
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account

# ========== ENV ==========
LINE_CHANNEL_TOKEN  = (os.getenv("LINE_CHANNEL_TOKEN") or os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
LINE_CHANNEL_SECRET = (os.getenv("LINE_CHANNEL_SECRET") or "").strip()
SERVICE_ACCOUNT_JSON_ENV = os.getenv("SERVICE_ACCOUNT_JSON", "").strip()
GOOGLE_DRIVE_FOLDER_ID   = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()

# 要呼叫的腳本（若你想直接沿用 line-4.py / lotto-line.py）
BET_SCRIPT   = os.getenv("BET_SCRIPT", "line-4.py")
PRIZE_SCRIPT = os.getenv("PRIZE_SCRIPT", "lotto-line.py")

# ========== Helpers ==========
def safe_reply(event, text):
    """回覆使用者，若 LINE 沒啟用就印出"""
    if line_bot_api:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))
    else:
        print(f"[MOCK reply] {text}")

def push_text(target_id: str, text: str):
    """推播訊息（用於背景任務完成後）"""
    if line_bot_api:
        line_bot_api.push_message(target_id, TextSendMessage(text=text))
    else:
        print(f"[MOCK push] {target_id}: {text}")

def get_target_id(event):
    """取得群組/聊天室/個人 ID"""
    return getattr(event.source, "group_id", None) \
        or getattr(event.source, "room_id", None) \
        or event.source.user_id

# ---- Drive ----
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def _load_service_info():
    raw = SERVICE_ACCOUNT_JSON_ENV
    if not raw and os.path.exists("credentials.json"):
        try:
            with open("credentials.json", "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception:
            pass
    if not raw:
        return None

    # 若是 base64
    if not raw.startswith("{"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except Exception:
            pass
    try:
        info = json.loads(raw)
        return info
    except Exception as e:
        print(f"⚠️ SERVICE_ACCOUNT_JSON 解析失敗：{e}")
        return None

def build_drive_service():
    info = _load_service_info()
    if not info:
        print("⚠️ 沒有 SERVICE_ACCOUNT_JSON，Drive 停用")
        return None
    need = {"type", "private_key", "client_email", "token_uri"}
    missing = need - set(info.keys())
    if missing:
        print(f"⚠️ Service account JSON 缺欄位：{missing}")
        return None
    try:
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        service = build("drive", "v3", credentials=creds)
        print("✅ Drive service ready")
        return service
    except Exception as e:
        print(f"⚠️ 建立 Drive service 失敗：{e}")
        return None

def upload_to_drive(service, file_path, folder_id=None):
    if not service:
        print("⚠️ Drive 未啟用，略過上傳")
        return None
    meta = {"name": os.path.basename(file_path)}
    if folder_id:
        meta["parents"] = [folder_id]
    media = MediaFileUpload(file_path, resumable=True)
    f = service.files().create(body=meta, media_body=media, fields='id').execute()
    return f"https://drive.google.com/file/d/{f['id']}/view"

drive_service = build_drive_service()

# ---- Background runner ----
def run_script_background(target_id: str, script: str, tag="JOB", extra_args=None):
    """用 subprocess 背景跑你的舊腳本 (line-4.py / lotto-line.py)"""
    def _worker():
        cmd = [sys.executable, script] + (extra_args or [])
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            if res.returncode != 0:
                push_text(target_id, f"⚠️ {tag} 失敗\n{res.stderr[:1500]}")
                return
            out = res.stdout.strip() or f"✅ {tag} 完成"
            push_text(target_id, out[-3500:])
        except Exception as e:
            push_text(target_id, f"⚠️ {tag} 發生錯誤：{e}")
    threading.Thread(target=_worker, daemon=True).start()

# ========== LINE init ==========
line_bot_api = None
handler      = None
if LINE_CHANNEL_TOKEN and LINE_CHANNEL_SECRET:
    line_bot_api = LineBotApi(LINE_CHANNEL_TOKEN)
    handler      = WebhookHandler(LINE_CHANNEL_SECRET)
    print("✅ LINE bot ready.")
else:
    print("⚠️ LINE_CHANNEL_TOKEN 或 LINE_CHANNEL_SECRET 未設定，LINE 功能停用。")

# ========== Flask ==========
app = Flask(__name__)

@app.route("/health")
def health():
    return "OK", 200

@app.route("/callback", methods=['POST'])
def callback():
    if not handler:
        return "LINE not configured", 503
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# ========== LINE Event ==========
if handler:
    @handler.add(MessageEvent, message=TextMessage)
    def handle_message(event):
        raw = event.message.text.strip()
        cmd = re.sub(r"[()（）\\s]", "", raw)  # 去除括號與空白
        target_id = get_target_id(event)

        # 注單
        if cmd == "注單":
            safe_reply(event, "📑 注單生成中，請稍候...")
            run_script_background(target_id, BET_SCRIPT, tag="注單報表")
            return

        # 對獎
        if cmd == "對獎":
            safe_reply(event, "🎯 對獎作業中，請稍候...")
            run_script_background(target_id, PRIZE_SCRIPT, tag="對獎")
            return

        # help
        if cmd in {"help", "?", "指令"}:
            safe_reply(event, "可用指令：\n(注單)  產生下注報表\n(對獎)  執行對獎流程\n(help)  顯示此說明")
            return

        # 預設 echo
        safe_reply(event, f"收到：{raw}")

# ========== main ==========
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
