import asyncio
from telegram import Bot

# 替换你的 BOT_TOKEN 和 STORAGE_CHANNEL_ID
BOT_TOKEN = "8875451128:AAFrrCkvRU7q9sQyYSPyOhWkuHmYqdYq504"
CHANNEL_ID = -1003915355673

async def test():
    bot = Bot(token=BOT_TOKEN)
    msg = await bot.send_message(chat_id=CHANNEL_ID, text="🤖 频道管道测试消息")
    print(f"发送成功！消息 ID 为: {msg.message_id}")

asyncio.run(test())
