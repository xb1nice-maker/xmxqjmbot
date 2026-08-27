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

SUPER_ADMIN_ID = 8762272568  

def is_admin_user(user_id: int, role: str) -> bool:
    return (user_id == SUPER_ADMIN_ID) or (user_id == ADMIN_ID) or (role in [ROLE_SUPER_ADMIN, ROLE_ADMIN])

async def check_user_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    user_id = user.id
    role = get_user_role(user_id)
    
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

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    db.add_user_if_not_exists(user_id)

    welcome_text = (
        "👋 **欢迎使用小马星球专属解码机器人！**\n"
        "⚠️ **非会员用户禁止使用，联系管理 @ipq123 购买**\n\n"
        "-----------------------------------\n"
        "📜 **使用规则：**\n"
        "1. 严禁上传/传输违规视频或文件！\n"
        "2. 可随时在【我上传的文件码】中更改资源的【可转发/防转发】属性。\n"
        "-----------------------------------\n\n"
        "👇 请选择下方的功能按钮，或直接发送 7 位表情提取码取件："
    )
    await update.message.reply_text(welcome_text, reply_markup=get_main_keyboard(role, user_id), parse_mode="Markdown")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    role = get_user_role(user_id)

    if role == ROLE_BLACKLIST or not await check_user_membership(update, context):
        return

    text = update.message.text.strip()
    db.add_user_if_not_exists(user_id)
    state = context.user_data.get("admin_state")

    if text == "➕ 添加管理员" and is_admin_user(user_id, role):
        context.user_data["admin_state"] = "awaiting_add_admin"
        await update.message.reply_text("➕ 请直接回复你想添加为管理员的**用户 ID**：")
        return

    if state == "awaiting_add_admin":
        context.user_data["admin_state"] = None
        if text.isdigit():
            db.set_user_role(int(text), 'admin')
            await update.message.reply_text(f"✅ 成功将用户 `{text}` 提升为管理员！", parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ 输入无效，必须为纯数字。")
        return

    if state == "awaiting_broadcast":
        context.user_data["admin_state"] = None
        await start_broadcast(update, context, text)
        return
    elif state == "awaiting_ban":
        context.user_data["admin_state"] = None
        if text.isdigit():
            db.ban_user(int(text))
            await update.message.reply_text(f"🚫 用户 `{text}` 已加入黑名单。", parse_mode="Markdown")
        return
    elif state == "awaiting_unban":
        context.user_data["admin_state"] = None
        if text.isdigit():
            db.unban_user(int(text))
            await update.message.reply_text(f"✅ 用户 `{text}` 已解封。", parse_mode="Markdown")
        return

    if text == "📦 多文件打包模式":
        context.user_data["packing_mode"] = True
        context.user_data["pack_files"] = []
        await update.message.reply_text(
            "📦 **已进入多文件打包模式！**\n发送完所有文件后，请点击下方按钮生成提取码。",
            reply_markup=get_packing_keyboard(), parse_mode="Markdown"
        )
        return

    elif text == "✅ 完成打包并生成提取码":
        if not context.user_data.get("packing_mode"):
            await update.message.reply_text("⚠️ 当前未处于打包模式。", reply_markup=get_main_keyboard(role, user_id))
            return
        files = context.user_data.get("pack_files", [])
        if not files:
            await update.message.reply_text("⚠️ 你还没有发送任何有效文件！")
            return
        
        # 默认打包创建时为允许转发，可在文件库里自行更改
        code = db.save_user_pack(user_id, files, protect_content=False)
        context.user_data["packing_mode"] = False
        context.user_data["pack_files"] = []
        await update.message.reply_text(
            f"🎉 **打包完成！**\n\n"
            f"• 包含文件：`{len(files)}` 个\n"
            f"• 属性：🟢 默认允许转发 *(可在文件库修改)*\n"
            f"• 表情提取码：`{code}`",
            reply_markup=get_main_keyboard(role, user_id),
            parse_mode="Markdown"
        )
        return

    elif text == "❌ 取消打包":
        context.user_data["packing_mode"] = False
        context.user_data["pack_files"] = []
        await update.message.reply_text("❌ 已取消打包。", reply_markup=get_main_keyboard(role, user_id))
        return

    elif text == "🔍 我上传的文件码":
        await render_my_files_page(update, context, user_id=user_id, page=1, is_new_message=True)
        return
    elif text == "☕️ 赞助机器人":
        await update.message.reply_text("☕️ 感谢支持！联系 @ipq123")
        return
    elif text == "⚙️ 管理员功能" and is_admin_user(user_id, role):
        await update.message.reply_text("⚙️ **管理员后台**", reply_markup=get_admin_keyboard(), parse_mode="Markdown")
        return
    elif text == "↩️ 返回主菜单":
        await update.message.reply_text("已返回主菜单：", reply_markup=get_main_keyboard(role, user_id))
        return
    elif text == "🗄️ 全局文件码库" and is_admin_user(user_id, role):
        await render_admin_global_packs_page(update, context, page=1, is_new_message=True)
        return

    else:
        pack = db.get_pack_by_code(text)
        if pack:
            if not is_admin_user(user_id, role):
                is_cd, remaining_sec = db.check_user_code_cooldown(user_id, text, hours=2)
                if is_cd:
                    mins = math.ceil(remaining_sec / 60)
                    await update.message.reply_text(f"⏳ 提取码冷却中，请等待 {mins} 分钟。", parse_mode="Markdown")
                    return
            
            protect = pack.get("protect_content", False)
            protect_text = "🔴 [不可转发/防盗]" if protect else "🟢 [允许转发]"
            await update.message.reply_text(f"📦 成功识别提取码：`{text}` {protect_text}\n🚀 正在推送资源...", parse_mode="Markdown")
            await send_batch_files(update, context, code=text, page=1, user_id=user_id, screen_group=0)
        else:
            await update.message.reply_text(f"❓ 未找到提取码：`{text}`")

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
        await update.message.reply_text("❌ 仅限管理员上传文件包。")
        return

    db.add_user_if_not_exists(user_id)
    msg = update.message
    file_type, file_id = "document", None
    is_valid = True

    try:
        if msg.photo: file_type, file_id = "photo", msg.photo[-1].file_id
        elif msg.video: file_type, file_id = "video", msg.video.file_id
        elif msg.audio: file_type, file_id = "audio", msg.audio.file_id
        elif msg.voice: file_type, file_id = "voice", msg.voice.file_id
        elif msg.document: file_type, file_id = "document", msg.document.file_id
        else: is_valid = False
    except Exception:
        is_valid = False

    if not is_valid or not file_id:
        await msg.reply_text("⚠️ 检测到问题文件，已自动去除！")
        return

    file_item = {"type": file_type, "file_id": file_id}

    if context.user_data.get("packing_mode"):
        if "pack_files" not in context.user_data: context.user_data["pack_files"] = []
        context.user_data["pack_files"].append(file_item)
        await msg.reply_text(f"⏳ 已缓存：`{len(context.user_data['pack_files'])}` 个文件", parse_mode="Markdown")
    else:
        # 单文件上传直接默认允许转发存入，可在文件库随时更改
        code = db.save_user_pack(user_id, [file_item], protect_content=False)
        await msg.reply_text(
            f"✅ **单文件转存成功！**\n\n"
            f"• 属性：🟢 允许转发\n"
            f"• 表情提取码：\n`{code}`\n\n"
            f"💡 提示：你可以点击【🔍 我上传的文件码】随时将它改为不可转发。",
            parse_mode="Markdown"
        )

# -------------------------------------------------------------
# 📤 发送带保护状态的文件逻辑
# -------------------------------------------------------------
async def send_batch_files(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str, page: int = 1, user_id: int = None, screen_group: int = None):
    chat_id = update.effective_chat.id
    pack = db.get_pack_by_code(code)
    if not pack:
        return

    if not user_id and update.effective_user:
        user_id = update.effective_user.id

    file_items = pack["files"]
    protect_content = pack.get("protect_content", False)
    total_files = len(file_items)
    chunk_size = 10
    total_pages = math.ceil(total_files / chunk_size)
    page = max(1, min(page, total_pages))
    
    max_buttons_per_screen = 15
    total_screen_groups = math.ceil(total_pages / max_buttons_per_screen)
    if screen_group is None:
        screen_group = (page - 1) // max_buttons_per_screen
    screen_group = max(0, min(screen_group, total_screen_groups - 1))

    start_idx = (page - 1) * chunk_size
    end_idx = min(start_idx + chunk_size, total_files)
    chunk = file_items[start_idx:end_idx]

    if page == 1 and user_id and not update.callback_query:
        db.update_user_code_extraction(user_id, code)

    if update.callback_query:
        waiting_msg = await context.bot.send_message(chat_id=chat_id, text=f"⏳ 准备第 {page}/{total_pages} 组...", parse_mode="Markdown")
        await asyncio.sleep(5.0)
        try: await waiting_msg.delete()
        except: pass

    failed_count = 0
    try:
        if len(chunk) == 1:
            item = chunk[0]
            f_id, f_type = item.get("file_id"), item.get("type", "document")
            if f_type == "photo": await context.bot.send_photo(chat_id=chat_id, photo=f_id, protect_content=protect_content)
            elif f_type == "video": await context.bot.send_video(chat_id=chat_id, video=f_id, protect_content=protect_content)
            elif f_type == "audio": await context.bot.send_audio(chat_id=chat_id, audio=f_id, protect_content=protect_content)
            elif f_type == "voice": await context.bot.send_voice(chat_id=chat_id, voice=f_id, protect_content=protect_content)
            else: await context.bot.send_document(chat_id=chat_id, document=f_id, protect_content=protect_content)
        else:
            media_group = []
            for item in chunk:
                f_id, f_type = item.get("file_id"), item.get("type", "document")
                if not f_id: continue
                if f_type == "photo": media_group.append(InputMediaPhoto(media=f_id))
                elif f_type == "video": media_group.append(InputMediaVideo(media=f_id))
                elif f_type == "audio": media_group.append(InputMediaAudio(media=f_id))
                else: media_group.append(InputMediaDocument(media=f_id))

            if media_group:
                try:
                    await context.bot.send_media_group(chat_id=chat_id, media=media_group, protect_content=protect_content)
                except Exception:
                    for item in chunk:
                        f_id, f_type = item.get("file_id"), item.get("type", "document")
                        try:
                            if f_type == "photo": await context.bot.send_photo(chat_id=chat_id, photo=f_id, protect_content=protect_content)
                            elif f_type == "video": await context.bot.send_video(chat_id=chat_id, video=f_id, protect_content=protect_content)
                            else: await context.bot.send_document(chat_id=chat_id, document=f_id, protect_content=protect_content)
                        except: failed_count += 1
    except Exception as e:
        logger.error(f"发送异常: {e}")

    buttons = []
    start_num = screen_group * max_buttons_per_screen + 1
    end_num = min(start_num + max_buttons_per_screen - 1, total_pages)
    current_row = []
    for p_num in range(start_num, end_num + 1):
        btn_text = f"[{p_num}]" if p_num == page else str(p_num)
        current_row.append(InlineKeyboardButton(btn_text, callback_data=f"sendpage_{code}_{p_num}_{screen_group}"))
        if len(current_row) == 5:
            buttons.append(current_row)
            current_row = []
    if current_row: buttons.append(current_row)

    block_nav_row = []
    if screen_group > 0: block_nav_row.append(InlineKeyboardButton("⬅️ 上一组", callback_data=f"block_{code}_{screen_group - 1}"))
    if screen_group < total_screen_groups - 1: block_nav_row.append(InlineKeyboardButton("下一组 ➡️", callback_data=f"block_{code}_{screen_group + 1}"))
    if block_nav_row: buttons.append(block_nav_row)
    buttons.append([InlineKeyboardButton("❌ 结束提取", callback_data="cancel_extract")])

    protect_label = "🔴 [不可转发]" if protect_content else "🟢 [允许转发]"
    status_msg = f"📦 提取码：`{code}` {protect_label}\n📊 页码：`{page}/{total_pages}`"
    await context.bot.send_message(chat_id=chat_id, text=status_msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

# -------------------------------------------------------------
# 📂 文件管理页面（带权限一键切换按钮）
# -------------------------------------------------------------
async def render_my_files_page(update, context, user_id, page=1, is_new_message=False):
    packs = db.get_user_packs(user_id)
    if not packs:
        text = "📂 你当前还没有上传过任何文件。"
        if is_new_message: await update.message.reply_text(text)
        else: await update.callback_query.edit_message_text(text)
        return

    per_page = 5
    total_pages = math.ceil(len(packs) / per_page)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    current_packs = packs[start_idx:start_idx + per_page]

    msg_text = f"📁 **我的文件码管理 (第 {page}/{total_pages} 页)**\n点击下方按钮可直接切换转发权限👇\n\n"
    inline_keyboard = []

    for item in current_packs:
        code, count = item["code"], item["count"]
        protect = item.get("protect_content", False)
        status_str = "🔴 禁止转发" if protect else "🟢 允许转发"
        
        msg_text += f"• 提取码：`{code}` ({count}个文件) | 状态：`{status_str}`\n"
        
        # 按钮行：1. 提取 2. 切换权限 3. 删除
        toggle_label = "🔓 设为允许转发" if protect else "🔒 设为禁止转发"
        inline_keyboard.append([
            InlineKeyboardButton(f"📥 提取", callback_data=f"get_{code}"),
            InlineKeyboardButton(toggle_label, callback_data=f"toggle_{code}_{page}")
        ])
        inline_keyboard.append([
            InlineKeyboardButton(f"🗑️ 删除该文件码", callback_data=f"del_{code}_{page}")
        ])

    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"page_{page-1}"))
    if page < total_pages: nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"page_{page+1}"))
    if nav_row: inline_keyboard.append(nav_row)

    markup = InlineKeyboardMarkup(inline_keyboard)
    if is_new_message: await update.message.reply_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    else: await update.callback_query.edit_message_text(msg_text, reply_markup=markup, parse_mode="Markdown")

async def render_admin_global_packs_page(update, context, page=1, is_new_message=False):
    all_packs = db.get_all_global_packs()
    if not all_packs:
        text = "🗄️ 全局文件码库为空。"
        if is_new_message: await update.message.reply_text(text)
        else: await update.callback_query.edit_message_text(text)
        return

    per_page = 5
    total_pages = math.ceil(len(all_packs) / per_page)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    current_packs = all_packs[start_idx:start_idx + per_page]

    msg_text = f"👑 **管理员全局文件码库 (第 {page}/{total_pages} 页)**\n\n"
    inline_keyboard = []

    for item in current_packs:
        owner, code, count = item["owner_id"], item["code"], item["count"]
        protect = item.get("protect_content", False)
        status_str = "🔴 禁止转发" if protect else "🟢 允许转发"
        
        msg_text += f"👤 用户: `{owner}` | 码: `{code}` ({count}个) | `{status_str}`\n"
        toggle_label = "🔓 允许" if protect else "🔒 禁止"
        inline_keyboard.append([
            InlineKeyboardButton(f"📥 {code}", callback_data=f"get_{code}"),
            InlineKeyboardButton(toggle_label, callback_data=f"adm_toggle_{code}_{page}"),
            InlineKeyboardButton(f"🗑️ 强删", callback_data=f"adm_del_{code}_{page}")
        ])

    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"adm_page_{page-1}"))
    if page < total_pages: nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"adm_page_{page+1}"))
    if nav_row: inline_keyboard.append(nav_row)

    markup = InlineKeyboardMarkup(inline_keyboard)
    if is_new_message: await update.message.reply_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    else: await update.callback_query.edit_message_text(msg_text, reply_markup=markup, parse_mode="Markdown")

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
    data = query.data
    role = get_user_role(user_id)
    is_admin = is_admin_user(user_id, role)

    await query.answer()

    # 💡 切换转发权限路由
    if data.startswith("toggle_") or data.startswith("adm_toggle_"):
        parts = data.split("_")
        is_adm_toggle = parts[0] == "adm"
        code = parts[2] if is_adm_toggle else parts[1]
        current_page = int(parts[3] if is_adm_toggle else parts[2])

        pack = db.get_pack_by_code(code)
        if pack:
            current_status = pack.get("protect_content", False)
            new_status = not current_status
            db.update_pack_protect_status(code, new_status)  # 更新数据库中的状态
            
            if is_adm_toggle:
                await render_admin_global_packs_page(update, context, page=current_page)
            else:
                await render_my_files_page(update, context, user_id=user_id, page=current_page)
        return

    if data.startswith("page_"):
        await render_my_files_page(update, context, user_id=user_id, page=int(data.split("_")[1]))
    elif data.startswith("adm_page_"):
        if is_admin:
            await render_admin_global_packs_page(update, context, page=int(data.split("_")[2]))
    elif data.startswith("del_"):
        _, code, current_page = data.split("_")
        db.delete_pack_by_code(code)
        await render_my_files_page(update, context, user_id=user_id, page=int(current_page))
    elif data.startswith("adm_del_"):
        if is_admin:
            _, _, code, current_page = data.split("_")
            db.delete_pack_by_code(code)
            await render_admin_global_packs_page(update, context, page=int(current_page))
    elif data.startswith("get_"):
        code = data.split("_")[1]
        await send_batch_files(update, context, code=code, page=1, user_id=user_id, screen_group=0)
    elif data.startswith("sendpage_"):
        _, code, page_str, screen_group_str = data.split("_")
        try: await query.message.edit_reply_markup(reply_markup=None)
        except: pass
        await send_batch_files(update, context, code=code, page=int(page_str), user_id=user_id, screen_group=int(screen_group_str))
    elif data == "cancel_extract":
        await query.message.edit_text("❌ 已结束提取。")