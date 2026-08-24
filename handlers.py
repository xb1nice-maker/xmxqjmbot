import math
import time
import random
import asyncio
import logging
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaDocument, InputMediaPhoto, InputMediaVideo, InputMediaAudio
)
from telegram.ext import ContextTypes
from permissions import get_user_role, ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_BLACKLIST
from config import REQUIRED_GROUP_ID, ADMIN_ID
import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 💡 请在此处填入你自己的 Telegram 账号数字 ID（作为最高权限超级管理员）
SUPER_ADMIN_ID = 8762272568  

def is_admin_user(user_id: int, role: str) -> bool:
    """辅助函数：统一判定用户是否具备管理员权限"""
    return (user_id == SUPER_ADMIN_ID) or (user_id == ADMIN_ID) or (role in [ROLE_SUPER_ADMIN, ROLE_ADMIN])

# -------------------------------------------------------------
# 🛡️ 加群状态校验
# -------------------------------------------------------------
async def check_user_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    
    user_id = user.id
    role = get_user_role(user_id)
    
    # 管理员豁免加群限制
    if is_admin_user(user_id, role):
        return True

    try:
        member = await context.bot.get_chat_member(chat_id=REQUIRED_GROUP_ID, user_id=user_id)
        if member.status in ["creator", "administrator", "member"]:
            return True
    except Exception as e:
        logger.error(f"⚠️ 检查群状态异常 [User: {user_id}]: {e}")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 联系客服/管理购买 VIP", url="https://t.me/ipq123")]
    ])
    
    msg_text = (
        "🚫 **访问受限！**\n\n"
        "检测到你尚未加入 **VIP 防失联群组**，禁止使用本机器人。\n\n"
        "⚠️ 本机器人仅限 VIP 会员使用，请联系客服/管理开通购买 VIP 权限后再试！"
    )

    try:
        if update.callback_query:
            await update.callback_query.message.reply_text(msg_text, reply_markup=keyboard, parse_mode="Markdown")
        elif update.message:
            await update.message.reply_text(msg_text, reply_markup=keyboard, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"发送未加群拦截消息失败: {e}")
        
    return False

# -------------------------------------------------------------
# ⌨️ 键盘布局
# -------------------------------------------------------------
def get_main_keyboard(user_role: str, user_id: int = 0):
    keyboard = [
        [KeyboardButton("📦 多文件打包模式"), KeyboardButton("🔍 我上传的文件码")],
        [KeyboardButton("☕️ 赞助机器人")]
    ]
    if is_admin_user(user_id, user_role):
        keyboard[1].append(KeyboardButton("⚙️ 管理员功能"))
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_packing_keyboard():
    keyboard = [
        [KeyboardButton("✅ 完成打包并生成提取码")],
        [KeyboardButton("❌ 取消打包")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard():
    keyboard = [
        [KeyboardButton("📊 系统统计数据"), KeyboardButton("🗄️ 全局文件码库")],
        [KeyboardButton("📢 广播消息"), KeyboardButton("🚫 拉黑用户"), KeyboardButton("✅ 解封用户")],
        [KeyboardButton("➕ 添加管理员"), KeyboardButton("↩️ 返回主菜单")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# -------------------------------------------------------------
# 🚀 指令与文本处理
# -------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ 处理 /start 指令 """
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    if not user:
        return
    user_id = user.id
    role = get_user_role(user_id)

    if role == ROLE_BLACKLIST:
        await update.message.reply_text("🚫 你已被列入黑名单，无法使用机器人。")
        return

    if not await check_user_membership(update, context):
        return

    context.user_data["packing_mode"] = False
    context.user_data["pack_files"] = []
    context.user_data["packing_progress_msg_id"] = None
    db.add_user_if_not_exists(user_id)

    welcome_text = (
        "👋 **欢迎使用小马星球专属解码机器人！**\n"
        "⚠️ **非会员用户禁止使用，联系管理 @ipq123 购买**\n\n"
        "-----------------------------------\n"
        "📜 **使用规则与注意事项：**\n"
        "1. 严禁上传/传输 **血腥、暴力、政治敏感** 等违规视频或文件！\n"
        "2. 一经发现违规使用，将**永久封禁账号**并清空全部文件！\n"
        "-----------------------------------\n\n"
        "💡 **快捷操作说明：**\n"
        "• **单文件**：直接发给我，我会立刻给你返回 7 位表情提取码！\n"
        "• **多文件**：点击【📦 多文件打包模式】，发完后点击完成打包。\n\n"
        "👇 请选择下方的功能按钮，或直接发送 7 位表情提取码取件："
    )

    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_keyboard(role, user_id),
        parse_mode="Markdown"
    )

async def cmd_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
        
    user_id = update.effective_user.id
    current_role = get_user_role(user_id)
    
    if not is_admin_user(user_id, current_role):
        await update.message.reply_text("❌ 您没有权限执行此操作。")
        return
        
    if not context.args:
        await update.message.reply_text("⚠️ 请指定要添加为管理员的用户 ID。\n用法：`/addadmin 目标用户ID`", parse_mode="Markdown")
        return
        
    try:
        target_user_id = int(context.args[0])
        db.set_user_role(target_user_id, 'admin')
        await update.message.reply_text(f"✅ 成功将用户 `{target_user_id}` 提升为**管理员**！", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ 用户 ID 格式不正确，必须是纯数字。")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    if not user:
        return
    user_id = user.id
    role = get_user_role(user_id)

    if role == ROLE_BLACKLIST:
        await update.message.reply_text("🚫 你已被列入黑名单，无法使用机器人功能。")
        return

    if not await check_user_membership(update, context):
        return

    text = update.message.text.strip()
    db.add_user_if_not_exists(user_id)

    state = context.user_data.get("admin_state")

    if text == "➕ 添加管理员":
        if not is_admin_user(user_id, role):
            await update.message.reply_text("❌ 您没有权限执行此操作。")
            return
        context.user_data["admin_state"] = "awaiting_add_admin"
        await update.message.reply_text(
            "➕ **添加管理员指引**\n\n"
            "请直接回复你想添加为管理员的**用户 ID**（纯数字）：",
            parse_mode="Markdown"
        )
        return

    if state == "awaiting_add_admin":
        context.user_data["admin_state"] = None
        if text.isdigit():
            target_id = int(text)
            db.set_user_role(target_id, 'admin')
            await update.message.reply_text(f"✅ 成功将用户 `{target_id}` 提升为**管理员**！", parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ 输入无效，用户 ID 必须为纯数字。")
        return

    if state == "awaiting_broadcast":
        context.user_data["admin_state"] = None
        await start_broadcast(update, context, text)
        return

    elif state == "awaiting_ban":
        context.user_data["admin_state"] = None
        if text.isdigit():
            target_id = int(text)
            db.ban_user(target_id)
            await update.message.reply_text(f"🚫 用户 `{target_id}` 已成功加入黑名单！", parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ 输入无效，用户 ID 必须为纯数字。")
        return

    elif state == "awaiting_unban":
        context.user_data["admin_state"] = None
        if text.isdigit():
            target_id = int(text)
            db.unban_user(target_id)
            await update.message.reply_text(f"✅ 用户 `{target_id}` 已从黑名单移出！", parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ 输入无效，用户 ID 必须为纯数字。")
        return

    if context.user_data.get("awaiting_page_jump"):
        context.user_data["awaiting_page_jump"] = False
        if text.isdigit():
            await render_my_files_page(update, context, user_id=user_id, page=int(text), is_new_message=True)
            return

    if text == "📦 多文件打包模式":
        context.user_data["packing_mode"] = True
        context.user_data["pack_files"] = []
        context.user_data["packing_progress_msg_id"] = None
        await update.message.reply_text(
            f"📦 **已进入多文件打包模式！**\n\n"
            f"现在你可以批量发送文件/图片/视频。\n"
            f"我会在收到文件时实时给你提示更新进度！\n"
            f"全部发送完毕后，请点击下方：\n"
            f"👇 **【✅ 完成打包并生成提取码】**",
            reply_markup=get_packing_keyboard(),
            parse_mode="Markdown"
        )
        return

    elif text == "✅ 完成打包并生成提取码":
        if not context.user_data.get("packing_mode"):
            await update.message.reply_text("⚠️ 当前未处于打包模式。", reply_markup=get_main_keyboard(role, user_id))
            return

        files = context.user_data.get("pack_files", [])
        if not files:
            await update.message.reply_text("⚠️ 你还没有发送任何文件！请先发送文件后再尝试打包。")
            return

        code = db.save_user_pack(user_id, files)
        logger.info(f"✅ 多文件打包入库成功 [User: {user_id}]: 表情码={code}, 文件数={len(files)}")

        context.user_data["packing_mode"] = False
        context.user_data["pack_files"] = []
        context.user_data["packing_progress_msg_id"] = None

        await update.message.reply_text(
            f"🎉 **全部件数已打包完成！**\n\n"
            f"• 成功打包：`{len(files)}` 个文件\n"
            f"• 表情提取码：`{code}`\n\n"
            f"👉 发送提取码 `{code}` 即可随时提取全部打包文件！",
            reply_markup=get_main_keyboard(role, user_id),
            parse_mode="Markdown"
        )
        return

    elif text == "❌ 取消打包":
        context.user_data["packing_mode"] = False
        context.user_data["pack_files"] = []
        context.user_data["packing_progress_msg_id"] = None
        await update.message.reply_text("❌ 已取消打包，临时缓存已清空。", reply_markup=get_main_keyboard(role, user_id))
        return

    elif text == "🔍 我上传的文件码":
        await render_my_files_page(update, context, user_id=user_id, page=1, is_new_message=True)
        return

    elif text == "☕️ 赞助机器人":
        await update.message.reply_text("☕️ 感谢你的支持！联系管理员 @ipq123 进行赞助。")
        return

    elif text == "⚙️ 管理员功能":
        if is_admin_user(user_id, role):
            await update.message.reply_text(
                "⚙️ **已进入管理员后台面板**\n请选择你需要进行的操作：",
                reply_markup=get_admin_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("⛔️ 权限不足，只有管理员才能访问。")
        return

    elif text == "↩️ 返回主菜单":
        await update.message.reply_text("已返回主菜单：", reply_markup=get_main_keyboard(role, user_id))
        return

    elif text in ["📊 系统统计数据", "👥 查看用户数量"] and is_admin_user(user_id, role):
        stats = db.get_system_stats()
        await update.message.reply_text(
            f"📊 **系统数据统计**\n\n"
            f"• 历史注册用户数：`{stats['total_users']}` 人\n"
            f"• 全局文件码总数：`{stats['total_packs']}` 个\n"
            f"• 当前黑名单人数：`{stats['total_banned']}` 人",
            parse_mode="Markdown"
        )
        return

    elif text == "🗄️ 全局文件码库" and is_admin_user(user_id, role):
        await render_admin_global_packs_page(update, context, page=1, is_new_message=True)
        return

    elif text == "📢 广播消息" and is_admin_user(user_id, role):
        context.user_data["admin_state"] = "awaiting_broadcast"
        await update.message.reply_text("📢 请在下方直接回复你想**群发广播的内容**：")
        return

    elif text == "🚫 拉黑用户" and is_admin_user(user_id, role):
        context.user_data["admin_state"] = "awaiting_ban"
        await update.message.reply_text("🚫 请回复你要拉黑的 **Telegram 用户 ID**（数字）：")
        return

    elif text == "✅ 解封用户" and is_admin_user(user_id, role):
        context.user_data["admin_state"] = "awaiting_unban"
        await update.message.reply_text("✅ 请回复你要解封的 **Telegram 用户 ID**（数字）：")
        return

    else:
        pack = db.get_pack_by_code(text)
        if pack:
            if not is_admin_user(user_id, role):
                is_cd, remaining_sec = db.check_user_code_cooldown(user_id, text, hours=2)
                if is_cd:
                    mins = math.ceil(remaining_sec / 60)
                    await update.message.reply_text(
                        f"⏳ **提取码冷却中**\n\n"
                        f"该提取码 `{text}` 在 2 小时内已被提取过！\n"
                        f"为了规避 Telegram 频率限制，请等待 **{mins} 分钟** 后再试。",
                        parse_mode="Markdown"
                    )
                    return

            await update.message.reply_text(
                f"📦 **成功识别提取码**：`{text}`\n"
                f"📦 **包含文件**：`{pack['count']}` 个\n"
                f"🚀 正在为您推送资源，请稍候...", 
                parse_mode="Markdown"
            )
            await send_batch_files(update, context, code=text, page=1, user_id=user_id)
        else:
            await update.message.reply_text(f"❓ 未找到提取码：`{text}`，请检查是否输入正确。")

# -------------------------------------------------------------
# 📥 存储逻辑（直接接收文件并缓存，无频道中转）
# -------------------------------------------------------------
async def handle_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    if not user:
        return
    user_id = user.id
    role = get_user_role(user_id)

    if role == ROLE_BLACKLIST or not await check_user_membership(update, context):
        return

    if not is_admin_user(user_id, role):
        await update.message.reply_text("❌ 抱歉，本机器人**仅限管理员**上传文件包。\n\n普通用户只能通过输入提取码来下载文件哦！")
        return

    db.add_user_if_not_exists(user_id)
    msg = update.message
    
    file_type = "document"
    file_id = None

    if msg.photo:
        file_type = "photo"
        file_id = msg.photo[-1].file_id
    elif msg.video:
        file_type = "video"
        file_id = msg.video.file_id
    elif msg.audio:
        file_type = "audio"
        file_id = msg.audio.file_id
    elif msg.voice:
        file_type = "voice"
        file_id = msg.voice.file_id
    elif msg.document:
        file_type = "document"
        file_id = msg.document.file_id

    if not file_id:
        await update.message.reply_text("⚠️ 未能识别到有效的文件内容。")
        return

    file_item = {
        "type": file_type, 
        "file_id": file_id
    }

    if context.user_data.get("packing_mode"):
        if "pack_files" not in context.user_data:
            context.user_data["pack_files"] = []
            
        current_files = context.user_data["pack_files"]
        MAX_PACK_FILES = 1500
        if len(current_files) >= MAX_PACK_FILES:
            await msg.reply_text(f"⚠️ 已达到单次打包上限 ({MAX_PACK_FILES} 个)！请点击【✅ 完成打包】。")
            return

        current_files.append(file_item)
        current_count = len(current_files)

        progress_msg_id = context.user_data.get("packing_progress_msg_id")
        status_text = (
            f"⏳ **正在缓存接收中...**\n"
            f"📦 当前已缓存：`{current_count}` 个文件\n\n"
            f"💡 发送完毕后，请点击下方【✅ 完成打包并生成提取码】。"
        )

        try:
            if progress_msg_id:
                await context.bot.edit_message_text(
                    chat_id=msg.chat_id,
                    message_id=progress_msg_id,
                    text=status_text,
                    parse_mode="Markdown"
                )
            else:
                sent_msg = await msg.reply_text(status_text, parse_mode="Markdown")
                context.user_data["packing_progress_msg_id"] = sent_msg.message_id
        except Exception as e:
            logger.warning(f"更新上传提示失败，重新发送: {e}")
            sent_msg = await msg.reply_text(status_text, parse_mode="Markdown")
            context.user_data["packing_progress_msg_id"] = sent_msg.message_id

    else:
        status_msg = await msg.reply_text("⏳ **正在处理并生成提取码...**", parse_mode="Markdown")
        try:
            code = db.save_user_pack(user_id, [file_item])
            logger.info(f"✅ 单文件入库成功 [User: {user_id}]: 表情码={code}")

            await status_msg.edit_text(
                f"✅ **文件转存成功！**\n\n"
                f"🎉 你的表情提取码为：\n`{code}`\n\n"
                f"💡 **使用方法**：在此对话框发送上面那串表情，即可直接提取文件！",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"❌ 保存文件失败: {e}")
            await status_msg.edit_text("❌ 保存文件失败，请稍后再试。")

# -------------------------------------------------------------
# 📢 辅助渲染与管理函数
# -------------------------------------------------------------
async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, broadcast_text: str):
    all_users = db.get_all_user_ids()
    await update.message.reply_text(f"⏳ 开始向 `{len(all_users)}` 名用户推送广播...", parse_mode="Markdown")
    success, failed = 0, 0
    for uid in all_users:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 **系统广播通知**\n\n{broadcast_text}", parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await update.message.reply_text(f"✅ 广播完毕！成功: `{success}`, 失败: `{failed}`", parse_mode="Markdown")

async def render_my_files_page(update, context, user_id, page=1, is_new_message=False):
    packs = db.get_user_packs(user_id)
    if not packs:
        text = "📂 你当前还没有上传过任何文件。（如果是打包上传，请确认已点击【✅ 完成打包并生成提取码】）"
        if is_new_message: await update.message.reply_text(text)
        else: await update.callback_query.edit_message_text(text)
        return

    per_page = 5
    total_pages = math.ceil(len(packs) / per_page)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    current_packs = packs[start_idx:start_idx + per_page]

    msg_text = f"📁 **我的文件码管理 (第 {page}/{total_pages} 页)**\n\n"
    inline_keyboard = []

    for item in current_packs:
        code, count = item["code"], item["count"]
        msg_text += f"• 表情码：`{code}` （包含 {count} 个文件）\n"
        inline_keyboard.append([
            InlineKeyboardButton(f"📥 提取 {code}", callback_data=f"get_{code}"),
            InlineKeyboardButton(f"🗑️ 删除 {code}", callback_data=f"del_{code}_{page}")
        ])

    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"page_{page-1}"))
    nav_row.append(InlineKeyboardButton("🎯 跳页", callback_data=f"jump_{page}"))
    if page < total_pages: nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"page_{page+1}"))
    inline_keyboard.append(nav_row)

    markup = InlineKeyboardMarkup(inline_keyboard)
    if is_new_message: await update.message.reply_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    else: await update.callback_query.edit_message_text(msg_text, reply_markup=markup, parse_mode="Markdown")

async def render_admin_global_packs_page(update, context, page=1, is_new_message=False):
    all_packs = db.get_all_global_packs()
    if not all_packs:
        text = "🗄️ 全局文件码库为空，当前没有任何用户上传文件。"
        if is_new_message: await update.message.reply_text(text)
        else: await update.callback_query.edit_message_text(text)
        return

    per_page = 5
    total_pages = math.ceil(len(all_packs) / per_page)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    current_packs = all_packs[start_idx:start_idx + per_page]

    msg_text = f"👑 **管理员专属 - 全局文件码数据库 (第 {page}/{total_pages} 页)**\n"
    msg_text += f"📊 系统的文件码总数：`{len(all_packs)}` 个\n\n"

    inline_keyboard = []
    for item in current_packs:
        owner, code, count = item["owner_id"], item["code"], item["count"]
        msg_text += f"👤 **用户 ID:** `{owner}`\n"
        msg_text += f"└ 提取码: `{code}` | 文件数: `{count}` 个\n\n"

        inline_keyboard.append([
            InlineKeyboardButton(f"📥 校验/提取 {code}", callback_data=f"get_{code}"),
            InlineKeyboardButton(f"🚫 强行删除 {code}", callback_data=f"adm_del_{code}_{page}")
        ])

    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"adm_page_{page-1}"))
    if page < total_pages: nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"adm_page_{page+1}"))
    if nav_row: inline_keyboard.append(nav_row)

    markup = InlineKeyboardMarkup(inline_keyboard)
    if is_new_message: await update.message.reply_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    else: await update.callback_query.edit_message_text(msg_text, reply_markup=markup, parse_mode="Markdown")

# -------------------------------------------------------------
# 📤 提取核心逻辑（具备自动跳过失效文件功能）
# -------------------------------------------------------------
async def send_batch_files(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str, page: int = 1, user_id: int = None):
    chat_id = update.effective_chat.id
    pack = db.get_pack_by_code(code)

    if not pack:
        text = "❌ 提取码已失效或被删除。"
        if update.callback_query: await update.callback_query.message.reply_text(text)
        else: await update.message.reply_text(text)
        return

    if not user_id and update.effective_user:
        user_id = update.effective_user.id

    file_items = pack["files"]
    total_files = len(file_items)
    chunk_size = 10
    total_pages = math.ceil(total_files / chunk_size)

    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * chunk_size
    end_idx = min(start_idx + chunk_size, total_files)

    chunk = file_items[start_idx:end_idx]

    if page == 1 and user_id:
        db.update_user_code_extraction(user_id, code)

    if page > 1:
        waiting_msg = await context.bot.send_message(
            chat_id=chat_id, 
            text=f"⏳ **正在准备第 {page}/{total_pages} 组文件，请等待 10 秒缓冲...**", 
            parse_mode="Markdown"
        )
        await asyncio.sleep(10.0)
        try:
            await waiting_msg.delete()
        except Exception:
            pass

    failed_count = 0
    try:
        if len(chunk) == 1:
            item = chunk[0]
            f_id = item.get("file_id")
            f_type = item.get("type", "document")
            
            try:
                if f_type == "photo":
                    await context.bot.send_photo(chat_id=chat_id, photo=f_id)
                elif f_type == "video":
                    await context.bot.send_video(chat_id=chat_id, video=f_id)
                elif f_type == "audio":
                    await context.bot.send_audio(chat_id=chat_id, audio=f_id)
                elif f_type == "voice":
                    await context.bot.send_voice(chat_id=chat_id, voice=f_id)
                else:
                    await context.bot.send_document(chat_id=chat_id, document=f_id)
            except Exception as single_err:
                logger.warning(f"⚠️ 单文件发送失败已跳过 [{f_id}]: {single_err}")
                failed_count += 1
        else:
            media_group = []
            for item in chunk:
                f_id = item.get("file_id")
                f_type = item.get("type", "document")

                if not f_id:
                    continue

                if f_type == "photo":
                    media_group.append(InputMediaPhoto(media=f_id))
                elif f_type == "video":
                    media_group.append(InputMediaVideo(media=f_id))
                elif f_type == "audio":
                    media_group.append(InputMediaAudio(media=f_id))
                else:
                    media_group.append(InputMediaDocument(media=f_id))

            if media_group:
                try:
                    await context.bot.send_media_group(chat_id=chat_id, media=media_group)
                except Exception as album_err:
                    logger.warning(f"⚠️ send_media_group 聚合发送失败: {album_err}，降级为逐个发送...")
                    for item in chunk:
                        f_id = item.get("file_id")
                        f_type = item.get("type", "document")
                        try:
                            if f_type == "photo":
                                await context.bot.send_photo(chat_id=chat_id, photo=f_id)
                            elif f_type == "video":
                                await context.bot.send_video(chat_id=chat_id, video=f_id)
                            elif f_type == "audio":
                                await context.bot.send_audio(chat_id=chat_id, audio=f_id)
                            elif f_type == "voice":
                                await context.bot.send_voice(chat_id=chat_id, voice=f_id)
                            else:
                                await context.bot.send_document(chat_id=chat_id, document=f_id)
                        except Exception as item_err:
                            logger.warning(f"⚠️ 忽略失效文件继续发送 [{f_id}]: {item_err}")
                            failed_count += 1

    except Exception as e:
        logger.error(f"❌ 提取推送批次主逻辑异常: {e}")

    warning_suffix = f"\n⚠️ *(其中有 {failed_count} 个文件因长期未调用已失效被自动跳过)*" if failed_count > 0 else ""

    buttons = []
    if page < total_pages:
        next_count = min(chunk_size, total_files - end_idx)
        buttons.append([InlineKeyboardButton(f"▶️ 发送下一组 ({end_idx + 1}-{end_idx + next_count}) [需等10秒]", callback_data=f"sendpage_{code}_{page + 1}")])
        buttons.append([InlineKeyboardButton("❌ 结束提取", callback_data="cancel_extract")])
    else:
        buttons.append([InlineKeyboardButton("✅ 已全部提取完毕", callback_data="cancel_extract")])

    markup = InlineKeyboardMarkup(buttons)
    status_msg = (
        f"📦 **提取码：** `{code}`\n"
        f"📊 **当前进度：** 已发送第 `{page}/{total_pages}` 组\n"
        f"📁 **本次推送：** 第 {start_idx + 1} ~ {end_idx} 个（共 {total_files} 个文件）"
        f"{warning_suffix}"
    )

    await context.bot.send_message(chat_id=chat_id, text=status_msg, reply_markup=markup, parse_mode="Markdown")

# -------------------------------------------------------------
# 🔀 Callback 路由
# -------------------------------------------------------------
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if not user:
        await query.answer()
        return
    user_id = user.id

    if not await check_user_membership(update, context):
        await query.answer()
        return

    role = get_user_role(user_id)
    data = query.data

    is_admin = is_admin_user(user_id, role)

    if data.startswith("sendpage_") and not is_admin:
        now = time.time()
        last_click = context.user_data.get("last_page_click_time", 0)
        cooldown = 10
        
        if now - last_click < cooldown:
            remaining = int(cooldown - (now - last_click))
            await query.answer(f"⏳ 正在接收或冷却中，请等待 {remaining} 秒后再点击！", show_alert=True)
            return
        context.user_data["last_page_click_time"] = now

    await query.answer()

    if data.startswith("page_"):
        await render_my_files_page(update, context, user_id=user_id, page=int(data.split("_")[1]))
    elif data.startswith("adm_page_"):
        if is_admin:
            await render_admin_global_packs_page(update, context, page=int(data.split("_")[2]))
    elif data.startswith("jump_"):
        context.user_data["awaiting_page_jump"] = True
        await query.message.reply_text("💬 请回复你想跳转到的**页码数字**：")

    elif data.startswith("del_"):
        _, code, current_page = data.split("_")
        db.delete_pack_by_code(code)
        await query.message.reply_text(f"✅ 提取码 `{code}` 已成功删除！", parse_mode="Markdown")
        await render_my_files_page(update, context, user_id=user_id, page=int(current_page))

    elif data.startswith("adm_del_"):
        if is_admin:
            _, _, code, current_page = data.split("_")
            db.delete_pack_by_code(code)
            await query.message.reply_text(f"👑 **管理员删码：** 提取码 `{code}` 已强行清空！", parse_mode="Markdown")
            await render_admin_global_packs_page(update, context, page=int(current_page))

    elif data.startswith("get_"):
        code = data.split("_")[1]
        
        if not is_admin:
            is_cd, remaining_sec = db.check_user_code_cooldown(user_id, code, hours=2)
            if is_cd:
                mins = math.ceil(remaining_sec / 60)
                await query.message.reply_text(
                    f"⏳ **提取码冷却中**\n\n"
                    f"该提取码 `{code}` 在 2 小时内已被提取过！\n"
                    f"请等待 **{mins} 分钟** 后再试。",
                    parse_mode="Markdown"
                )
                return

        await send_batch_files(update, context, code=code, page=1, user_id=user_id)

    elif data.startswith("sendpage_"):
        _, code, page_str = data.split("_")
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await send_batch_files(update, context, code=code, page=int(page_str), user_id=user_id)

    elif data == "cancel_extract":
        await query.message.edit_text("❌ 已结束本次文件提取。")