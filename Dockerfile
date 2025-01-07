# 运行时作为父镜像
FROM python:3.8-slim

# 设置工作目录
WORKDIR /app

# 安装 Flask
RUN pip install Flask

# 安装 pytest 和 pytest-cov
RUN pip install pytest requests pytest-cov
RUN pip install coverage pytest pytest-cov

# 复制当前目录内容到容器中的工作目录
COPY . /app

# 暴露端口 6007
EXPOSE 6007

# 运行应用
CMD ["flask", "run", "--host=0.0.0.0", "--port=6007"]