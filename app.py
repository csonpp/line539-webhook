import os
import sys
import subprocess
import re
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
    # 想新增腳本只需在此加入 '指令': '檔名.py'
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

    # 顯示伺服器環境
    cwd = os.getcwd()
    files = os.listdir(cwd)
    print(f"🔍 Current working dir: {cwd}")
    print(f"🔍 Files in cwd: {files}")

    # 如果使用者輸入 id，回傳 userId
    if txt.lower() == 'id':
        user_id = event.source.user_id or event.source.group_id
        reply = f"你的 userId：{user_id}"
    else:
        executed = False
        reply = None
        for trigger, script in COMMAND_SCRIPTS.items():
            if trigger in txt:
                print(f"🔍 Trigger '{trigger}' matched, attempt to run script: {script}")
                executed = True
                # 檢查檔案是否存在
                if not os.path.isfile(os.path.join(cwd, script)):
                    print(f"❌ Script file not found: {script}")
                    reply = f"找不到腳本檔: {script}"
                else:
                    try:
                        result = subprocess.run(
                            [sys.executable, script],
                            cwd=cwd,
                            capture_output=True,
                            text=True,
                            timeout=120
                        )
                        # Debug process details
                        print(f"🔍 {script} returncode: {result.returncode}")
                        print(f"🔍 {script} stdout: {result.stdout!r}")
                        print(f"🔍 {script} stderr: {result.stderr!r}")

                        if result.returncode == 0:
                            output = result.stdout.strip() or '(程式執行完成，無輸出)'
                            reply = f"{script} 執行完成：\n{output}"
                        else:
                            # 如果 stderr 空，就回傳 stdout
                            err_msg = result.stderr.strip() or result.stdout.strip()
                            reply = f"{script} 執行失敗 (returncode={result.returncode})：\n{err_msg}"
                    except subprocess.TimeoutExpired:
                        print(f"❌ Timeout expired when running {script}")
                        reply = f"執行 {script} 超時，請稍後再試。"
                    except Exception as e:
                        print(f"❌ Exception running {script}: {e}")
                        reply = f"執行 {script} 發生例外：{e}"
                break
        if not executed:
            print("🔍 No command trigger matched, echo back.")
            reply = txt

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
