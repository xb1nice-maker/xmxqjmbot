import random
import json
import logging
from datetime import datetime
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from config import DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EMOJI_POOL = [
    "🔥", "🚀", "🎁", "⭐", "🎉", "💎", "🍿", "🍔", "🍕", "🍰",
    "🍦", "🍩", "⚽️", "🏀", "🎮", "🎯", "🎲", "🎨", "🎭", "🎪",
    "🎫", "👑", "🏆", "🥇", "🐱", "🐶", "🐼", "🦊", "🐯"
]

# -------------------------------------------------------------
# 🔌 数据库连接池初始化
# -------------------------------------------------------------
try:
    db_pool = pool.ThreadedConnectionPool(1, 20, DATABASE_URL)
    logger.info("✅ 数据库连接池初始化成功！")
except Exception as e:
    logger.error(f"❌ 数据库连接池初始化失败: {e}")
    db_pool = None

def get_connection():
    if db_pool:
        return db_pool.getconn()
    return psycopg2.connect(DATABASE_URL)

def release_connection(conn):
    if db_pool and conn:
        db_pool.putconn(conn)
    elif conn:
        conn.close()

def generate_emoji_code(length=7):
    return "".join(random.choices(EMOJI_POOL, k=length))

# -------------------------------------------------------------
# 🛠️ 数据库表初始化
# -------------------------------------------------------------
def init_db():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # 用户表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    role VARCHAR(20) DEFAULT 'user',
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 文件包主表（已增加 protect_content 字段存储转发权限）
            cur.execute("""
                CREATE TABLE IF NOT EXISTS file_bundles (
                    code VARCHAR(50) PRIMARY KEY,
                    user_id BIGINT,
                    file_id TEXT,
                    files TEXT,
                    file_count INT DEFAULT 1,
                    protect_content BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 💡 兼容老数据库：如果表已存在但没有 protect_content 字段，自动执行补全
            cur.execute("""
                ALTER TABLE file_bundles 
                ADD COLUMN IF NOT EXISTS protect_content BOOLEAN DEFAULT FALSE;
            """)

            # 用户独立提取记录表（用于实现每个用户独立的 2 小时冷却）
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_extractions (
                    user_id BIGINT,
                    code VARCHAR(50),
                    last_extracted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, code)
                );
            """)

            # 为 user_id 创建索引
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_file_bundles_user_id 
                ON file_bundles(user_id);
            """)

            conn.commit()
            logger.info("✅ 数据库表结构与索引初始化完成！")
    except Exception as e:
        logger.error(f"❌ 数据库初始化失败: {e}")
        conn.rollback()
    finally:
        release_connection(conn)

# -------------------------------------------------------------
# ⏱️ 用户独立提取码 CD 判定逻辑
# -------------------------------------------------------------
def check_user_code_cooldown(user_id: int, code: str, hours: int = 2):
    """检查特定用户对特定提取码的独立冷却状态[cite: 1]"""
    conn = get_connection()
    try:
        user_id = int(user_id)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    last_extracted_at,
                    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - last_extracted_at)) AS elapsed
                FROM user_extractions 
                WHERE user_id = %s AND code = %s;
            """, (user_id, code))
            row = cur.fetchone()
            
            if not row or not row[0]:
                return False, 0
            
            elapsed_seconds = row[1]
            cooldown_seconds = hours * 3600

            if elapsed_seconds < cooldown_seconds:
                remaining = int(cooldown_seconds - elapsed_seconds)
                return True, remaining
            return False, 0
    except Exception as e:
        logger.error(f"检查用户提取码 CD 失败: {e}")
        return False, 0
    finally:
        release_connection(conn)

def update_user_code_extraction(user_id: int, code: str):
    """更新特定用户最后提取该码的时间[cite: 1]"""
    conn = get_connection()
    try:
        user_id = int(user_id)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_extractions (user_id, code, last_extracted_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, code) 
                DO UPDATE SET last_extracted_at = CURRENT_TIMESTAMP;
            """, (user_id, code))
            conn.commit()
    except Exception as e:
        logger.error(f"更新用户提取时间失败: {e}")
        conn.rollback()
    finally:
        release_connection(conn)

# -------------------------------------------------------------
# 👤 用户与权限管理
# -------------------------------------------------------------
def add_user_if_not_exists(user_id: int):
    conn = get_connection()
    try:
        user_id = int(user_id)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id) 
                VALUES (%s) 
                ON CONFLICT (user_id) DO NOTHING;
            """, (user_id,))
            conn.commit()
    except Exception as e:
        logger.error(f"添加用户失败: {e}")
        conn.rollback()
    finally:
        release_connection(conn)

def is_banned(user_id: int) -> bool:
    conn = get_connection()
    try:
        user_id = int(user_id)
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE user_id = %s;", (user_id,))
            row = cur.fetchone()
            return True if row and row[0] == 'blacklist' else False
    except Exception as e:
        logger.error(f"检查黑名单状态失败: {e}")
        return False
    finally:
        release_connection(conn)

def get_user_role_from_db(user_id: int) -> str:
    conn = get_connection()
    try:
        user_id = int(user_id)
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE user_id = %s;", (user_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else "user"
    except Exception as e:
        logger.error(f"获取用户角色失败: {e}")
        return "user"
    finally:
        release_connection(conn)

def ban_user(user_id: int):
    conn = get_connection()
    try:
        user_id = int(user_id)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, role) 
                VALUES (%s, 'blacklist') 
                ON CONFLICT (user_id) DO UPDATE SET role = 'blacklist';
            """, (user_id,))
            conn.commit()
    except Exception as e:
        logger.error(f"拉黑用户失败: {e}")
        conn.rollback()
    finally:
        release_connection(conn)

def unban_user(user_id: int):
    conn = get_connection()
    try:
        user_id = int(user_id)
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET role = 'user' WHERE user_id = %s;", (user_id,))
            conn.commit()
    except Exception as e:
        logger.error(f"解封用户失败: {e}")
        conn.rollback()
    finally:
        release_connection(conn)

def get_all_user_ids():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users;")
            rows = cur.fetchall()
            return [r[0] for r in rows]
    except Exception as e:
        logger.error(f"获取所有用户ID失败: {e}")
        return []
    finally:
        release_connection(conn)

def set_user_role(user_id: int, role: str):
    conn = get_connection()
    try:
        user_id = int(user_id)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, role) 
                VALUES (%s, %s) 
                ON CONFLICT (user_id) DO UPDATE SET role = %s;
            """, (user_id, role, role))
            conn.commit()
            logger.info(f"✅ 成功将用户 {user_id} 的角色设为: {role}")
    except Exception as e:
        logger.error(f"❌ 设置用户角色失败: {e}")
        conn.rollback()
    finally:
        release_connection(conn)

# -------------------------------------------------------------
# 📦 文件包与提取码管理
# -------------------------------------------------------------
def save_user_pack(user_id: int, files: list, protect_content: bool = False) -> str:
    """保存用户上传的文件包，支持传入 protect_content 转发权限"""
    init_db()
    conn = get_connection()
    try:
        clean_user_id = int(user_id)
        files_json = json.dumps(files, ensure_ascii=False)
        first_msg_id = str(files[0]["msg_id"]) if files and "msg_id" in files[0] else "0"

        for _ in range(10):
            code = generate_emoji_code()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO file_bundles (code, user_id, file_id, files, file_count, protect_content)
                        VALUES (%s, %s, %s, %s, %s, %s);
                    """, (code, clean_user_id, first_msg_id, files_json, len(files), protect_content))
                    conn.commit()
                    logger.info(f"✅ 数据库成功写入，提取码: {code}，用户ID: {clean_user_id}，防转发: {protect_content}")
                    return code
            except psycopg2.IntegrityError:
                conn.rollback()
                continue
                
        raise RuntimeError("无法生成唯一的提取码（尝试次数过多）")
    except Exception as e:
        logger.error(f"❌ 写入 file_bundles 数据库失败: {e}")
        conn.rollback()
        raise e
    finally:
        release_connection(conn)

def update_pack_protect_status(code: str, protect_status: bool):
    """更新指定提取码的转发保护状态"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE file_bundles 
                SET protect_content = %s 
                WHERE code = %s;
            """, (protect_status, code))
            conn.commit()
            logger.info(f"✅ 成功更新提取码 {code} 的防转发状态为: {protect_status}")
    except Exception as e:
        logger.error(f"❌ 更新提取码保护状态失败: {e}")
        conn.rollback()
    finally:
        release_connection(conn)

def get_user_packs(user_id: int):
    conn = get_connection()
    try:
        clean_user_id = int(user_id)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT code, files, file_id, created_at, protect_content
                FROM file_bundles 
                WHERE user_id = %s 
                ORDER BY created_at DESC;
            """, (clean_user_id,))
            rows = cur.fetchall()
            
            results = []
            for r in rows:
                files_data = []
                if r.get("files"):
                    files_data = json.loads(r["files"]) if isinstance(r["files"], str) else r["files"]
                elif r.get("file_id"):
                    files_data = [{"file_id": r["file_id"], "type": "document"}]
                    
                results.append({
                    "code": r["code"],
                    "count": len(files_data),
                    "protect_content": r.get("protect_content", False)
                })
            logger.info(f"🔍 查询用户 {clean_user_id} 的上传记录，查到 {len(results)} 条记录")
            return results
    except Exception as e:
        logger.error(f"❌ 获取用户提取码列表失败: {e}")
        return []
    finally:
        release_connection(conn)

def get_pack_by_code(code: str):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM file_bundles WHERE code = %s;", (code,))
            row = cur.fetchone()
            if not row:
                return None
            
            files_data = []
            if row.get("files"):
                files_data = json.loads(row["files"]) if isinstance(row["files"], str) else row["files"]
            elif row.get("file_id"):
                files_data = [{"file_id": row["file_id"], "type": "document"}]

            return {
                "code": row["code"],
                "owner_id": row.get("user_id"),
                "count": len(files_data),
                "files": files_data,
                "protect_content": row.get("protect_content", False)
            }
    except Exception as e:
        logger.error(f"读取提取码失败: {e}")
        return None
    finally:
        release_connection(conn)

def get_all_global_packs():
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT code, user_id, files, file_id, protect_content 
                FROM file_bundles 
                ORDER BY created_at DESC;
            """)
            rows = cur.fetchall()
            
            results = []
            for r in rows:
                files_data = []
                if r.get("files"):
                    files_data = json.loads(r["files"]) if isinstance(r["files"], str) else r["files"]
                elif r.get("file_id"):
                    files_data = [{"file_id": r["file_id"], "type": "document"}]
                    
                results.append({
                    "code": r["code"],
                    "owner_id": r["user_id"],
                    "count": len(files_data),
                    "protect_content": r.get("protect_content", False)
                })
            return results
    except Exception as e:
        logger.error(f"获取全局提取码失败: {e}")
        return []
    finally:
        release_connection(conn)

def delete_pack_by_code(code: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM file_bundles WHERE code = %s;", (code,))
            cur.execute("DELETE FROM user_extractions WHERE code = %s;", (code,))
            conn.commit()
    except Exception as e:
        logger.error(f"删除提取码失败: {e}")
        conn.rollback()
    finally:
        release_connection(conn)

def get_system_stats():
    conn = get_connection()
    stats = {"total_users": 0, "total_packs": 0, "total_banned": 0}
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM users) AS total_users,
                    (SELECT COUNT(*) FROM file_bundles) AS total_packs,
                    (SELECT COUNT(*) FROM users WHERE role = 'blacklist') AS total_banned;
            """)
            row = cur.fetchone()
            if row:
                stats["total_users"], stats["total_packs"], stats["total_banned"] = row
    except Exception as e:
        logger.error(f"获取系统统计失败: {e}")
    finally:
        release_connection(conn)
    return stats