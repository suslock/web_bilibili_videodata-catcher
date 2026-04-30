import asyncio
import logging
from functools import wraps
from typing import Callable, Any


def retry(max_attempts: int = 3, delay: float = 2.0, backoff: float = 2.0):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if "412" in str(e) or "风控" in str(e):
                        wait_time = 30 * attempt
                        logging.warning(f"⚠️ 触发风控，等待{wait_time}秒后重试...")
                    elif attempt < max_attempts:
                        wait_time = delay * (backoff ** (attempt - 1))
                        logging.warning(f"{func.__name__} 第{attempt}次失败，{wait_time:.1f}秒后重试")
                    else:
                        logging.error(f"{func.__name__} 重试{max_attempts}次后仍失败: {e}")
                        break

                    if attempt < max_attempts:
                        await asyncio.sleep(wait_time)
            raise last_exception

        return wrapper

    return decorator