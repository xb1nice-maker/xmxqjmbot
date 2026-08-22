import os
import logging
import asyncio
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
from aiohttp import web
from config import BOT_TOKEN
from database import init_db
from handlers import (
    cmd_start, cmd_add_admin, handle_text, handle_files, callback_router
)

# 设置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 获取 Render 环境变量
PORT = int(os.environ.get("PORT", "8080"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

async def health_check(request):
    """给 UptimeRobot 用的存活监测接口"""
    return web.Response(text="Bot is running!")

def main():
    print("1. 正在尝试连接并初始化 Supabase 数据库...")
    try:
        init_db()
        print("✅ Supabase 数据库初始化与数据表校验成功！")
    except Exception as e:
        print(f"❌ 数据库连接或初始化失败: {e}")
        return

    print("2. 正在构建 Telegram 机器人应用...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # 注册处理器
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("addadmin", cmd_add_admin))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE,
        handle_files
    ))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))

    # 逻辑判断：如果配置了 WEBHOOK_URL 则启动 Web 模式，否则轮询
    if WEBHOOK_URL:
        print("🚀 启动 Webhook 模式 (适合 Render + UptimeRobot)...")
        
        async def run_webhook():
            await app.initialize()
            await app.bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
            
            web_app = web.Application()
            # UptimeRobot 访问这个接口来保持活跃
            web_app.router.add_get("/", health_check)
            
            # Telegram 转发接口
            async def telegram_webhook(request):
                data = await request.json()
                from telegram import Update
                update = Update.de_json(data, app.bot)
                await app.process_update(update)
                return web.Response(text="OK")
            
            web_app.router.add_post(f"/{BOT_TOKEN}", telegram_webhook)
            
            runner = web.AppRunner(web_app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", PORT)
            await site.start()
            print(f"✅ Web 服务已在端口 {PORT} 启动")
            await asyncio.Event().wait()

        asyncio.run(run_webhook())
    else:
        print("🚀 未检测到 WEBHOOK_URL，以传统轮询模式运行...")
        app.run_polling()

if __name__ == "__main__":
    main()