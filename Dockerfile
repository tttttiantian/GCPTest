# 运行时作为父镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 复制requirements.txt
COPY requirements.txt /app/

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install pytest pytest-cov coverage

# 复制当前目录内容到容器中的工作目录
COPY . /app

# 暴露端口 6007
EXPOSE 6007

# 使用Gunicorn运行（支持70并发）
CMD ["gunicorn", "-c", "gunicorn_config.py", "app:app"]
