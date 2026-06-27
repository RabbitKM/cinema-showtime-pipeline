FROM python:3.12-slim

# 安裝 Google Chrome Stable
# vscinemas 需要 channel="chrome" 繞過 Akamai bot detection；
# miramar / skcinemas 用 playwright install 安裝的 Chromium。
RUN apt-get update && apt-get install -y wget gnupg ca-certificates && \
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" \
      > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && apt-get install -y google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安裝 Playwright Chromium（miramar/skcinemas 使用）
RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "main.py", "--load"]
