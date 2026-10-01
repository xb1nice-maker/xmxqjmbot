import os
import logging
import asyncio
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
from telegram import Update
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

# 全局存储所有克隆机器人的应用实例，方便管理和随时删除
active_cloned_apps = {}

async def health_check(request):
    """给 UptimeRobot 用的存活监测接口"""
    return web.Response(text="Bot is running!")

async def start_single_cloned_bot(token: str):
    """安全地初始化并启动单个克隆机器人，带有防崩溃保护"""
    if token in active_cloned_apps:
        return True
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
        # 使用极简安全的轮询，并加上超时捕获
        asyncio.create_task(run_safe_polling(clone_app, token))
        
        active_cloned_apps[token] = clone_app
        print(f"🤖 成功加载克隆机器人实例: {token[:10]}...")
        return True
    except Exception as e:
        logger.error(f"❌ 加载克隆机器人 {token[:10]} 失败: {e}")
        return False

async def run_safe_polling(app, token):
    """独立的非阻塞轮询包装器，防止单个 Bot 崩坏影响全局"""
    try:
        await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"⚠️ 克隆机器人 {token[:10]} 轮询中断: {e}")
        if token in active_cloned_apps:
            del active_cloned_apps[token]

async def stop_single_cloned_bot(token: str):
    """安全地停止并卸载一个克隆机器人"""
    if token in active_cloned_apps:
        try:
            app = active_cloned_apps[token]
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
            del active_cloned_apps[token]
            print(f"🗑️ 已成功安全卸载克隆机器人: {token[:10]}...")
        except Exception as e:
            logger.error(f"卸载克隆机器人异常: {e}")

async def sync_cloned_bots():
    """从数据库同步并启动所有克隆机器人"""
    cloned_bots = get_all_cloned_bots()
    current_tokens = {item["token"] for item in cloned_bots}
    
    # 启动数据库中存在但内存中没有的
    for item in cloned_bots:
        t = item["token"]
        if t not in active_cloned_apps:
            await start_single_cloned_bot(t)
            
    # 停止内存中有但数据库里已经被删掉的
    running_tokens = list(active_cloned_apps.keys())
    for t in running_tokens:
        if t not in current_tokens:
            await stop_single_cloned_bot(t)

def main():
    print("1. 正在尝试连接并初始化 Supabase 数据库...")
    try:
        init_db()
        print("✅ Supabase 数据库初始化与数据表校验成功！")
    except Exception as e:
        print(f"❌ 数据库连接或初始化失败: {e}")
        return

    print("2. 正在构建主 Telegram 机器人应用...")
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
        await sync_cloned_bots()

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
                update = Update.de_json(data, app.bot)
                await app.process_update(update)
                return web.Response(text="OK")
            
            web_app.router.add_post(f"/{BOT_TOKEN}", telegram_webhook)
            
            runner = web.AppRunner(web_app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", PORT)
            await site.start()
            print(f"✅ Web 服务已在端口 {PORT} 启动")
            
            # 启动并同步克隆机器人
            await sync_cloned_bots()
            
            await asyncio.Event().wait()

        asyncio.run(run_webhook())
    else:
        print("🚀 以轮询模式运行主 Bot...")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()