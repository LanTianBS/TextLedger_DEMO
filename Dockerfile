# 使用官方 Python 3.11 映像檔
FROM python:3.11-slim

# 安裝 ffmpeg 及其他必要套件
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 設定工作目錄
WORKDIR /app

# 複製專案檔案
COPY . /app

# 安裝 Python 依賴
RUN pip install --no-cache-dir -r requirements.txt

# 設定環境變數（可依需求調整）
ENV PYTHONUNBUFFERED=1

# 啟動 Flask 應用（請依實際啟動指令調整）
CMD ["python", "main.py"]
