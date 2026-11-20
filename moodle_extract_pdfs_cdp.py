#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moodle extractor via existing Chromium CDP session.
- Reuses logged-in session at http://127.0.0.1:9222
- Crawls known UNSW course pages
- Downloads newly discovered PDFs into /home/colin/Unsw/{COURSE}/{Lectures|Tutorials}
- Downloads selected non-PDF study files (.ipynb/.zip/.csv) into /home/colin/Unsw/{COURSE}/Materials/{ipynb|zip|csv}
- Writes summary to /tmp/moodle_pdf_extract_report.json
"""

import asyncio
import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright

CDP_URL = "http://127.0.0.1:9222"
BASE = "https://moodle.telt.unsw.edu.au"
OUT_REPORT = "/tmp/moodle_pdf_extract_report.json"

COURSES = {
    "COMP9900": "101528",
    "COMP4418": "101506",
    "COMP6714": "101516",
}

ROOT_DIR = Path("/home/colin/Unsw")
PLUGINFILE_RE = re.compile(r"https://moodle\.telt\.unsw\.edu\.au/pluginfile\.php[^\"'\s>]+", re.I)
ALLOWED_OTHER_EXTS = {".ipynb", ".zip", ".csv"}


def sanitize_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:180] or "file"


def infer_category(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["assignment", "homework", "rubric", "project"]):
        return "Assignments"
    if any(k in t for k in ["tutorial", "tut", "lab", "exercise", "worksheet"]):
        return "Tutorials"
    return "Lectures"


def ext_from_url(url: str) -> str:
    path = urlparse(url).path
    return Path(path).suffix.lower()


def filename_from_url(url: str) -> str:
    path = urlparse(url).path
    base = os.path.basename(path) or "resource"
    return sanitize_filename(base)


async def collect_links_on_page(page):
    js = r'''() => {
      const out = [];
      const seen = new Set();
      const anchors = [...document.querySelectorAll('a[href]')];
      for (const a of anchors) {
        const href = a.href || '';
        const text = (a.textContent || '').replace(/\s+/g,' ').trim();
        if (!href) continue;
        if (seen.has(href)) continue;
        seen.add(href);
        out.push({href, text});
      }
      return out;
    }'''
    return await page.evaluate(js)


async def resolve_resource_link(context, page, url: str) -> str:
    """Resolve mod/resource/view.php to final pluginfile/real file URL when possible."""
    # 1) fast path via authenticated request body parse
    try:
        resp = await context.request.get(url, timeout=45000)
        ctype = (resp.headers.get("content-type") or "").lower()
        if resp.ok and ("pdf" in ctype):
            # view.php may redirect straight to the pluginfile URL; keep the final .pdf URL
            return resp.url if "pluginfile.php" in resp.url else url
        if resp.ok:
            txt = await resp.text()
            m = PLUGINFILE_RE.findall(txt)
            if m:
                return html.unescape(m[0])
    except Exception:
        pass

    # 2) fallback: inspect rendered page links/embeds
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(800)
        arr = await page.evaluate(r'''() => {
            const out = [];
            const els = [...document.querySelectorAll('a[href],iframe[src],embed[src],object[data]')];
            for (const el of els) {
              const href = el.href || el.src || el.data || '';
              if (!href) continue;
              out.push(href);
            }
            return out;
        }''')
        for h in arr:
            hl = (h or "").lower()
            if "pluginfile.php" in hl:
                return h
            if ".pdf" in hl or any(hl.endswith(ext) for ext in ALLOWED_OTHER_EXTS):
                return h
    except Exception:
        pass

    return ""


async def download_file(context, url: str, out_path: Path, require_pdf: bool = False) -> bool:
    try:
        resp = await context.request.get(url, timeout=45000)
        if not resp.ok:
            return False
        ctype = (resp.headers.get("content-type") or "").lower()
        data = await resp.body()

        if require_pdf:
            if ("pdf" not in ctype) and (".pdf" not in url.lower()) and (not data.startswith(b"%PDF")):
                return False

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        return True
    except Exception:
        return False


async def main():
    report = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "Australia/Sydney",
        "downloaded": [],
        "downloaded_other": [],
        "skipped_existing": 0,
        "errors": [],
    }

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        if not browser.contexts:
            raise RuntimeError("No browser context available on CDP")
        context = browser.contexts[0]

        page = None
        for pg in context.pages:
            if "moodle.telt.unsw.edu.au" in (pg.url or ""):
                page = pg
                break
        if page is None:
            page = await context.new_page()

        await page.goto(f"{BASE}/my/", wait_until="domcontentloaded", timeout=45000)
        title = (await page.title()).lower()
        if "log in" in title or "login" in title:
            raise RuntimeError("Moodle login expired")

        for code, cid in COURSES.items():
            course_url = f"{BASE}/course/view.php?id={cid}"
            try:
                await page.goto(course_url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(1200)
            except Exception as e:
                report["errors"].append(f"{code}: failed to open course page: {e}")
                continue

            links = await collect_links_on_page(page)
            candidates = []
            for l in links:
                href = l["href"]
                txt = l.get("text", "")
                hl = href.lower()
                if (
                    ".pdf" in hl
                    or "mod/resource/view.php" in hl
                    or "pluginfile.php" in hl
                    or any(ext in hl for ext in ALLOWED_OTHER_EXTS)
                ):
                    candidates.append((href, txt, infer_category(txt)))
                elif "mod/folder/view.php" in hl:
                    try:
                        await page.goto(href, wait_until="domcontentloaded", timeout=45000)
                        await page.wait_for_timeout(800)
                        folder_links = await collect_links_on_page(page)
                        for fl in folder_links:
                            fhref = fl["href"]
                            ftxt = fl.get("text", "")
                            fhl = fhref.lower()
                            if (
                                ".pdf" in fhl
                                or "pluginfile.php" in fhl
                                or "mod/resource/view.php" in fhl
                                or any(ext in fhl for ext in ALLOWED_OTHER_EXTS)
                            ):
                                candidates.append((fhref, ftxt or txt, infer_category(ftxt or txt)))
                    except Exception as e:
                        report["errors"].append(f"{code}: folder parse fail {href}: {e}")
                    finally:
                        try:
                            await page.goto(course_url, wait_until="domcontentloaded", timeout=45000)
                            await page.wait_for_timeout(500)
                        except Exception:
                            pass

            uniq = {}
            for href, txt, cat in candidates:
                uniq[href] = (txt, cat)

            for href, (txt, cat) in uniq.items():
                raw_url = urljoin(BASE, href)
                final_url = raw_url

                # Resolve resource-view pages to final target first.
                if "mod/resource/view.php" in raw_url:
                    resolved = await resolve_resource_link(context, page, raw_url)
                    if not resolved:
                        report["errors"].append(f"{code}: resolve failed {raw_url}")
                        continue
                    final_url = resolved

                ext = ext_from_url(final_url)

                # PDF path (still only Lectures/Tutorials)
                if ".pdf" in final_url.lower() or ext == ".pdf":
                    if cat not in {"Lectures", "Tutorials"}:
                        continue
                    fname = sanitize_filename(txt) if txt and len(txt) > 3 else filename_from_url(final_url)
                    if not fname.lower().endswith(".pdf"):
                        fname += ".pdf"
                    out = ROOT_DIR / code / cat / fname
                    if out.exists():
                        report["skipped_existing"] += 1
                        continue
                    ok = await download_file(context, final_url, out, require_pdf=True)
                    if ok:
                        report["downloaded"].append({
                            "course": code,
                            "category": cat,
                            "file": str(out),
                            "source": final_url,
                        })
                    else:
                        report["errors"].append(f"{code}: download failed {final_url}")
                    continue

                # Selected non-PDF study files into dedicated directory.
                if ext in ALLOWED_OTHER_EXTS:
                    fname = sanitize_filename(txt) if txt and len(txt) > 3 else filename_from_url(final_url)
                    if not fname.lower().endswith(ext):
                        fname = f"{fname}{ext}"
                    out = ROOT_DIR / code / "Materials" / ext.lstrip(".") / fname
                    if out.exists():
                        report["skipped_existing"] += 1
                        continue
                    ok = await download_file(context, final_url, out, require_pdf=False)
                    if ok:
                        report["downloaded_other"].append({
                            "course": code,
                            "type": ext.lstrip("."),
                            "file": str(out),
                            "source": final_url,
                        })
                    else:
                        report["errors"].append(f"{code}: download failed {final_url}")
                    continue

        await browser.close()

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"DOWNLOAD={len(report['downloaded'])}")
    print(f"DOWNLOAD_OTHER={len(report['downloaded_other'])}")
    print(f"SKIPPED={report['skipped_existing']}")
    print(f"ERRORS={len(report['errors'])}")


if __name__ == "__main__":
    asyncio.run(main())
