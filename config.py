import os
from dotenv import load_dotenv

# 加载 .env 环境变量（如果存在）
load_dotenv()

# ==================== Bot 基础配置 ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_NAME = "小🐴星球专用bot"
BOT_USERNAME = os.getenv("BOT_USERNAME", "xmxqjm02_bot")

# ==================== 权限与频道配置 ====================
# 管理员 ID
ADMIN_ID = int(os.getenv("ADMIN_ID", "8409736325"))

# VIP 防失联群组 ID
REQUIRED_GROUP_ID = int(os.getenv("REQUIRED_GROUP_ID", "-1001577873050"))

# 私有文件存储频道 ID
STORAGE_CHANNEL_ID = int(os.getenv("STORAGE_CHANNEL_ID", "-1003915355673"))

# ==================== Supabase 数据库配置 ====================
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres.squfzvgffrwcjjlysjnw"),
    "password": os.getenv("DB_PASS", "xb1nice74511"),
    "host": os.getenv("DB_HOST", "aws-0-ap-northeast-1.pooler.supabase.com"),
    "port": int(os.getenv("DB_PORT", "6543"))
}

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
)