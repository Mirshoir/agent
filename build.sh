#!/bin/bash
set -e

echo "=== Building Instaagent on Render ==="

# Update pip and setuptools
pip install --upgrade pip setuptools wheel

# Install with only pre-built wheels (no compilation)
if ! pip install --only-binary :all: \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    pydantic==2.5.0 \
    pillow==10.4.0 \
    numpy==2.1.0 \
    requests==2.31.0 \
    supabase==2.3.4 \
    python-multipart==0.0.6 \
    python-telegram-bot==20.5 \
    aiohttp==3.9.1 \
    yt-dlp; then
  echo "Pre-built wheel installation had issues, trying alternative approach..."
  pip install \
    fastapi==0.99.0 \
    uvicorn[standard]==0.23.0 \
    pydantic==2.4.2 \
    pillow==10.4.0 \
    numpy==2.1.0 \
    requests==2.31.0 \
    supabase==2.3.4 \
    python-multipart==0.0.6 \
    python-telegram-bot==20.5 \
    aiohttp==3.9.1 \
    yt-dlp
fi

echo "=== Build complete ==="
