# 使用 Python 官方镜像作为基础镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# ==========================================
# 【核心步骤】安装 Node.js
# ==========================================
# 更新包列表并安装 nodejs 和 npm
# 注意：Debian/Ubuntu 源中的 nodejs 可能版本较旧，但运行 signer.js 足够了
RUN apt-get update && \
    apt-get install -y nodejs npm && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 验证 Node.js 是否安装成功 (可选，用于调试构建日志)
RUN node -v

# 复制当前目录下的相关文件到容器的工作目录
COPY ./parser /app/parser
COPY ./templates /app/templates
COPY ./utils /app/utils
COPY ./requirements.txt /app/
COPY ./main.py /app/


# 安装 Python 应用程序所需的依赖包
RUN pip install --no-cache-dir -r requirements.txt

# 暴露 FastAPI 应用程序的端口
EXPOSE 8000

# 启动 FastAPI 应用程序
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
