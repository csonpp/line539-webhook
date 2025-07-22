# app.py
# ------------------------------
# Robust env loading for LINE & Drive
# ------------------------------

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import os, json, base64
from flask import Flask, request, abort

# LINE Bot SDK (v2)
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# Google Drive API
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account

# ===== Util: load service account from ENV or file =====
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def load_service_account():
    raw = os.getenv("SERVICE_ACCOUNT_JSON", "").strip()

    # No ENV -> try file as last resort
    if not raw:
        print("⚠️ SERVICE_ACCOUNT_JSON not found, will try credentials.json ...")
        if os.path.exists("credentials.json"):
            try:
                with open("credentials.json", "r", encoding="utf-8") as f:
                    raw = f.read()
            except Exception as e:
                print(f"⚠️ credentials.json read error: {e}")
        else:
            return None

    # Maybe it's base64?
    if not raw.startswith("{"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except Exception:
            pass  # not base64

    try:
        info = json.loads(raw)
    except Exception as e:
        print(f"⚠️ 無法解析 SERVICE_ACCOUNT_JSON：{e}")
        return None

    # Minimal key check
    required_keys = {"type", "private_key", "client_email", "token_uri"}
    if not required_keys.issubset(info.keys()):
        print(f"⚠️ JSON 缺少必要欄位：{required_keys - set(info.keys())}")
        return None

    try:
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"⚠️ 建立 Drive Service 失敗：{e}")
        return None

# ===== Init Drive =====
drive_service = load_service_account()
if drive_service:
    print("✅ Drive service ready.")
else:
    print("⚠️ Drive disabled.")

# ===== Init LINE =====
LINE_CHANNEL_TOKEN  = os.getenv("LINE_CHANNEL_TOKEN", "").strip()
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "").strip()

LINE_CHANNEL_TOKEN  = (os.getenv("LINE_CHANNEL_TOKEN") or 
                       os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
LINE_CHANNEL_SECRET = (os.getenv("LINE_CHANNEL_SECRET") or "").strip()

line_bot_api = None
handler      = None
if LINE_CHANNEL_TOKEN and LINE_CHANNEL_SECRET:
    line_bot_api = LineBotApi(LINE_CHANNEL_TOKEN)
    handler      = WebhookHandler(LINE_CHANNEL_SECRET)
    print("✅ LINE bot ready.")
else:
    print("⚠️ LINE_CHANNEL_TOKEN 或 LINE_CHANNEL_SECRET 未設定，LINE 功能停用。")

# ===== Flask app =====
app = Flask(__name__)

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

if handler:
    @handler.add(MessageEvent, message=TextMessage)
    def handle_message(event):
        text = event.message.text.strip()
        # TODO: 你的對獎/指令邏輯
        reply = f"收到：{text}"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def upload_to_drive(file_path: str, folder_id: str = None) -> str | None:
    if not drive_service:
        print("⚠️ Drive 未啟用，略過上傳")
        return None
    meta = {'name': os.path.basename(file_path)}
    if folder_id:
        meta['parents'] = [folder_id]
    media = MediaFileUpload(file_path, resumable=True)
    file = drive_service.files().create(body=meta, media_body=media, fields='id').execute()
    return f"https://drive.google.com/file/d/{file['id']}/view"

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
