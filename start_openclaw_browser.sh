#!/bin/bash
set -euo pipefail

echo "🚀 启动 OpenClaw 浏览器（带调试端口）..."

if [ -z "${DISPLAY:-}" ]; then
  for d in :0 :1 :10; do
    if DISPLAY="$d" xset q >/dev/null 2>&1; then
      export DISPLAY="$d"
      break
    fi
  done
fi

if [ -z "${DISPLAY:-}" ]; then
  echo "❌ 未检测到图形会话"
  exit 1
fi

echo "检测到 DISPLAY=$DISPLAY"

# 检查是否已有进程占用
if [ -f /home/colin/.openclaw-browser-data/SingletonLock ]; then
  echo "⚠️ 检测到已有浏览器实例运行"
  echo "请先关闭现有浏览器，然后重新运行此脚本"
  exit 1
fi

python3 <<'PY'
import asyncio
from playwright.async_api import async_playwright
import os

USER_DATA_DIR = '/home/colin/.openclaw-browser-data'
CDP_PORT = 9222

async def main():
    print("启动浏览器...")
    
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            args=[
                '--start-maximized',
                '--no-sandbox',
                f'--remote-debugging-port={CDP_PORT}',
            ],
            viewport=None,
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto('https://moodle.telt.unsw.edu.au/')
        
        print(f"\n✅ 浏览器已启动（CDP 端口: {CDP_PORT}）")
        print("📌 登录 Moodle 后，浏览器会自动保持会话")
        print("📌 按 Ctrl+C 退出时浏览器会关闭但数据保留")
        print("\n保持此窗口运行，另开终端执行检查脚本...")
        
        try:
            while True:
                await asyncio.sleep(60)
        except KeyboardInterrupt:
            print("\n保存会话并退出...")
            await context.close()

asyncio.run(main())
PY
