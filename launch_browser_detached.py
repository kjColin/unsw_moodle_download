#!/usr/bin/env python3
"""Launch the CDP browser detached from any terminal.

Why not start_openclaw_browser.sh: that script runs in the foreground inside a
gnome-terminal, so closing the terminal (or losing the RDP session) kills the
browser — and with it the in-memory MoodleSession cookie, which is never
written to disk. Started via setsid, this survives both.
"""
import asyncio
from playwright.async_api import async_playwright

USER_DATA_DIR = '/home/colin/.openclaw-browser-data'
CDP_PORT = 9222

async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            args=['--start-maximized', '--no-sandbox',
                  f'--remote-debugging-port={CDP_PORT}'],
            viewport=None,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto('https://moodle.telt.unsw.edu.au/')
        while True:
            await asyncio.sleep(3600)

asyncio.run(main())
