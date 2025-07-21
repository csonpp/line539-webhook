# -------------------------
# app.py (完整範例)
# -------------------------

# 如果有安裝 python-dotenv，就讀取 .env；沒有也不會報錯
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import os
import json
import re
import sys
import smtplib
import requests
from datetime import datetime, timedelta
from copy import deepcopy
from bs4 import BeautifulSoup
from email.message import EmailMessage

from flask import Flask, request, abort

# LINE Bot SDK
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# Google Drive API
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account

# ====== 設定區 ======
LINE_CHANNEL_TOKEN  = os.getenv("LINE_CHANNEL_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

# 原本：從 credentials.json 檔案讀
# -----------------------------------
# SERVICE_ACCOUNT_FILE = "credentials.json"
# creds = service_account.Credentials.from_service_account_file(
#     SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/drive.file']
# )
# drive_service = build('drive', 'v3', credentials=creds)
# -----------------------------------
#
# 現在：從環境變數 SERVICE_ACCOUNT_JSON 讀取
SCOPES = ['https://www.googleapis.com/auth/drive.file']
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")

drive_service = None
if SERVICE_ACCOUNT_JSON:
    try:
        info  = json.loads(SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        drive_service = build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"⚠️ 無法解析 SERVICE_ACCOUNT_JSON：{e}")
else:
    print("⚠️ 找不到 SERVICE_ACCOUNT_JSON，Drive 功能將略過")

# ====== 初始化 LINE Bot ======
line_bot_api = LineBotApi(LINE_CHANNEL_TOKEN)
handler       = WebhookHandler(LINE_CHANNEL_SECRET)

app = Flask(__name__)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text

    # 在這裡放你「對獎」或其他業務邏輯
    # TODO: 把原本的對獎函式呼叫進來
    reply = f"收到訊息：{user_text}，功能待實作"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

def upload_to_drive(file_path: str, folder_id: str = None) -> str:
    """
    將指定檔案上傳到 Google Drive，並回傳檔案分享連結。
    如果 drive_service 是 None，就跳過上傳並回傳 None。
    """
    if not drive_service:
        print("⚠️ 無法獲得驅動力，上傳功能將略過")
        return None

    metadata = {'name': os.path.basename(file_path)}
    if folder_id:
        metadata['parents'] = [folder_id]

    media = MediaFileUpload(file_path, resumable=True)
    file  = drive_service.files().create(
        body=metadata, media_body=media, fields='id'
    ).execute()
    return f"https://drive.google.com/file/d/{file.get('id')}/view"

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
