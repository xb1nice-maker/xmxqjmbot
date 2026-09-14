import os
import logging
import asyncio
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
from aiohttp import web
from config import BOT_TOKEN
from database import init_db, get_all_cloned_bots
from handlers import (
    cmd_start, cmd_add_admin, handle_text, handle_files, callback_router
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", "8080"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

async def health_check(request):
    """给 UptimeRobot 用的存活监测接口"""
    return web.Response(text="Bot is running!")

async def start_single_cloned_bot(token: str, main_app):
    """单独异步拉起一个克隆机器人的实例，共享主机器人的 handlers 逻辑"""
    try:
        clone_app = ApplicationBuilder().token(token).build()
        
        clone_app.add_handler(CommandHandler("start", cmd_start))
        clone_app.add_handler(CommandHandler("addadmin", cmd_add_admin))
        clone_app.add_handler(CallbackQueryHandler(callback_router))
        clone_app.add_handler(MessageHandler(
            filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE,
            handle_files
        ))
        clone_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))

        await clone_app.initialize()
        await clone_app.start()
        await clone_app.updater.start_polling(drop_pending_updates=True)
        print(f"🤖 成功启动克隆机器人实例: {token[:10]}...")
    except Exception as e:
        logger.error(f"❌ 启动克隆机器人 {token[:10]} 失败: {e}")

async def start_all_cloned_bots(main_app):
    """启动数据库中所有的克隆机器人"""
    cloned_bots = get_all_cloned_bots()
    if not cloned_bots:
        return
    print(f"🔄 正在后台异步启动 {len(cloned_bots)} 个历史克隆机器人...")
    for item in cloned_bots:
        asyncio.create_task(start_single_cloned_bot(item["token"], main_app))

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

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("addadmin", cmd_add_admin))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE,
        handle_files
    ))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))

    async def post_init(application):
        await start_all_cloned_bots(application)

    app.post_init = post_init

    if WEBHOOK_URL:
        print("🚀 启动 Webhook 模式 (适合 Render + UptimeRobot)...")
        
        async def run_webhook():
            await app.initialize()
            await app.bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
            
            web_app = web.Application()
            web_app.router.add_get("/", health_check)
            
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
            
            # 同时拉起克隆机器人
            await start_all_cloned_bots(app)
            
            await asyncio.Event().wait()

        asyncio.run(run_webhook())
    else:
        print("🚀 未检测到 WEBHOOK_URL，以传统轮询模式运行...")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()