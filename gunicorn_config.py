"""
Gunicorn配置文件 - 用于生产环境部署
"""
import multiprocessing
import os

# 服务器绑定地址（0.0.0.0允许外部访问，127.0.0.1仅本机）
bind = "0.0.0.0:6007"

# Worker进程数（根据CPU核心数调整）
# 公式：workers = (CPU核心数 * 2) + 1
# 对于70并发：建议10个worker
workers = int(os.environ.get('GUNICORN_WORKERS', min(multiprocessing.cpu_count() * 2 + 1, 10)))

# 每个Worker的线程数
threads = int(os.environ.get('GUNICORN_THREADS', 7))

# Worker类型（sync为同步，gevent/eventlet为异步）
worker_class = "sync"

# 超时时间（秒）- 测试生成可能需要较长时间
timeout = 300  # 5分钟

# 优雅重启超时
graceful_timeout = 30

# 日志配置
accesslog = "-"  # 输出到stdout
errorlog = "-"   # 输出到stderr
loglevel = "info"

# 进程名
proc_name = "test_generator"

# 最大请求数（防止内存泄漏，处理完指定请求后重启worker）
max_requests = 1000
max_requests_jitter = 50

# 守护进程模式（False表示前台运行）
daemon = False

# 工作目录
chdir = os.path.dirname(os.path.abspath(__file__))

# 预加载应用（提高性能，但调试时建议关闭）
preload_app = False

# 环境变量
raw_env = [
    'PYTHONUNBUFFERED=1'
]

# Worker连接数限制
worker_connections = 1000

# Keep-alive时间
keepalive = 5

# 日志格式
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
