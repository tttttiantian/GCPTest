"""
令牌桶限流算法 - 用于控制GLM API调用速率
"""
import time
from threading import Lock


class TokenBucket:
    """令牌桶限流算法"""

    def __init__(self, rate: int, capacity: int):
        """
        Args:
            rate: 每秒生成的令牌数
            capacity: 桶容量
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_time = time.time()
        self.lock = Lock()

    def acquire(self, tokens: int = 1) -> bool:
        """尝试获取令牌"""
        with self.lock:
            now = time.time()
            # 补充令牌
            elapsed = now - self.last_time
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.rate
            )
            self.last_time = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def wait_for_token(self, tokens: int = 1, timeout: float = 30):
        """阻塞等待令牌"""
        start = time.time()
        while time.time() - start < timeout:
            if self.acquire(tokens):
                return True
            time.sleep(0.1)
        return False
