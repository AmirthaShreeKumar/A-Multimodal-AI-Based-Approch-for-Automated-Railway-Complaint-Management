import time
from collections import deque
from functools import wraps
from flask import request, jsonify

class RateLimiter:
    def __init__(self, limit: int, window: int):
        """
        :param limit: Maximum number of requests allowed
        :param window: Time window in seconds
        """
        self.limit = limit
        self.window = window
        self.requests = {}

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        if key not in self.requests:
            self.requests[key] = deque()
        
        # Remove expired requests
        while self.requests[key] and self.requests[key][0] < now - self.window:
            self.requests[key].popleft()
        
        if len(self.requests[key]) < self.limit:
            self.requests[key].append(now)
            return True
        return False

# Global limiters
ai_limiter = RateLimiter(limit=5, window=60)  # 5 AI calls per minute
chat_limiter = RateLimiter(limit=10, window=60) # 10 chat messages per minute

def limit_ai(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == "POST":
            user_ip = request.remote_addr
            if not ai_limiter.is_allowed(user_ip):
                return jsonify({
                    "ok": False, 
                    "error": "Rate limit exceeded. Please wait a minute before filing another complaint."
                }), 429
        return f(*args, **kwargs)
    return decorated_function

def limit_chat(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_ip = request.remote_addr
        if not chat_limiter.is_allowed(user_ip):
            return jsonify({
                "error": "You're chatting too fast! Take a short break."
            }), 429
        return f(*args, **kwargs)
    return decorated_function
