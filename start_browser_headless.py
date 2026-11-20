import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            '/home/colin/.openclaw-browser-data',
            headless=True,
            args=['--no-sandbox', '--remote-debugging-port=9222', '--headless=new'],
        )
        print('BROWSER_UP', flush=True)
        while True:
            await asyncio.sleep(60)

asyncio.run(main())
