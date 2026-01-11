# SF6 Chapter - Local Processor Docker Image
# Python 3.11 slim base image for minimal size
FROM python:3.11-slim

# システム依存のインストール
# - libgl1, libglib2.0-0: OpenCV依存
# - curl, unzip: Denoインストール用
# - ffmpeg: yt-dlp動画処理用
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    curl \
    unzip \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Denoのインストール（yt-dlp用JavaScriptランタイム）
RUN curl -fsSL https://deno.land/install.sh | sh && \
    ln -s /root/.deno/bin/deno /usr/local/bin/deno

# uvのインストール（公式イメージからコピー）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 作業ディレクトリ設定
WORKDIR /app

# Python依存関係ファイルをコピー（レイヤーキャッシュ最適化）
COPY pyproject.toml uv.lock README.md main.py ./

# Python依存関係をインストール（本番用、開発依存は除外）
RUN uv sync --frozen --no-dev

# アプリケーションコードをコピー
COPY src ./src
COPY config ./config

# yt-dlp設定ファイルを作成（Denoをデフォルトランタイムに設定）
RUN mkdir -p /root/.config/yt-dlp && \
    echo "--js-runtimes deno:/usr/local/bin/deno" > /root/.config/yt-dlp/config

# Pythonバッファリング無効化（ログをリアルタイム出力）
ENV PYTHONUNBUFFERED=1

# デフォルトコマンド: 常駐モードで起動
CMD ["uv", "run", "python", "main.py", "--mode", "daemon"]
