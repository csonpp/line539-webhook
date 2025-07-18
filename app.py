import os
import sys
import subprocess
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, JoinEvent

app = Flask(__name__)

# 從環境變數讀取 Channel Token & Secret
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET       = os.getenv("LINE_CHANNEL_SECRET")
if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise RuntimeError("請設定環境變數 LINE_CHANNEL_ACCESS_TOKEN 與 LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler       = WebhookHandler(LINE_CHANNEL_SECRET)

# 指令對應腳本
COMMAND_SCRIPTS = {
    '注單': 'line-4.py',       # 執行 line-4.py
    '對獎': 'lotto-line.py',   # 執行 lotto-line.py
}

# Webhook 接收路由
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body      = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 處理 Bot 被邀請進群組事件
@handler.add(JoinEvent)
def handle_join(event):
    gid   = event.source.group_id if event.source.type == 'group' else None
    reply = f"Bot 已加入群組，本群組 ID：{gid}"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# 處理收到文字訊息事件，自動辨識指令並執行對應動作
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    txt = event.message.text.strip()
    print(f"🔍 Received message text: '{txt}'")  # Debug log

    # 先處理 English 'id' 指令
    if txt.lower() == 'id':
        user_id = event.source.user_id or event.source.group_id
        reply = f"你的 userId：{user_id}"
    else:
        # 處理自訂命令
        executed = False
        for trigger, script in COMMAND_SCRIPTS.items():
            if trigger in txt:
                try:
                    # 使用同 Python 直譯器執行對應腳本
                    result = subprocess.run(
                        [sys.executable, script],
                        cwd=os.getcwd(), capture_output=True, text=True, timeout=60
                    )
                    if result.returncode == 0:
                        output = result.stdout.strip() or '(程式執行完成，無輸出)'
                        reply = f"{script} 執行完成：\n{output}"
                    else:
                        reply = f"{script} 執行失敗：\n{result.stderr.strip()}"
                except Exception as e:
                    reply = f"執行 {script} 發生例外：{e}"
                executed = True
                break
        # 如果沒有命令觸發，就原文回覆
        if not executed:
            reply = txt

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
