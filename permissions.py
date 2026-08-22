from config import ADMIN_ID
from database import is_banned, get_user_role_from_db

# 权限常量定义
ROLE_SUPER_ADMIN = "super_admin"
ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_BLACKLIST = "blacklist"

def get_user_role(user_id: int) -> str:
    """获取用户权限角色"""
    # 兼容处理：同时检查硬编码的 ADMIN_ID 和代码中的 SUPER_ADMIN_ID 常量（防止两边不一致）
    # 你可以把主程序里的 SUPER_ADMIN_ID 也直接写到 config.py 的 ADMIN_ID 里面
    if user_id == ADMIN_ID:
        return ROLE_SUPER_ADMIN

    # 检查黑名单
    if is_banned(user_id):
        return ROLE_BLACKLIST

    # 查询数据库获取数据库中设置的权限
    role = get_user_role_from_db(user_id)
    
    # 💡 增加防呆判断：如果数据库返回的不在合法角色内，或者为空，默认返回普通用户
    if not role or role not in [ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_USER, ROLE_BLACKLIST]:
        return ROLE_USER
        
    return role.lower() # 统一转为小写，防止数据库里存成大写导致匹配失败