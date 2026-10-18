FROM python:3.12-bookworm

ARG TARGETARCH
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

# Xvfb 虚拟显示器 + 中文字体 + Chrome(amd64)/Chromium(arm64)
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb xauth tzdata wget ca-certificates fonts-noto-cjk scrot \
    && if [ "$TARGETARCH" = "arm64" ]; then \
         apt-get install -y --no-install-recommends chromium ; \
       else \
         wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
         && apt-get install -y --no-install-recommends /tmp/chrome.deb \
         && rm /tmp/chrome.deb ; \
       fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ /app/

CMD ["python", "main.py"]
