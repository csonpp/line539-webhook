import os
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

# Webhook 接收
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
    reply = f"強哥的 Bot 加入群組囉！本群組ID：{gid}"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# 處理收到訊息事件
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    txt = event.message.text.strip()
    print(f"🔍 Received message text: '{txt}'")  # Debug log
    # 如果使用者輸入 id（不區分大小寫），回傳他的 userId
    if txt.lower() == "id":
        user_id = event.source.user_id or event.source.group_id
        reply = f"你的 userId：{user_id}"
    else:
        # 否則就原封不動把文字回給他
        reply = txt

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
