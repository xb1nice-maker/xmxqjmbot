import random
import string
from database import get_file

def generate_code(length=6):
    """生成唯一提取码"""

    while True:
        code = ''.join(
            random.choices(
                string.ascii_uppercase + string.digits,
                k=length
            )
        )

        if get_file(code) is None:
            return code