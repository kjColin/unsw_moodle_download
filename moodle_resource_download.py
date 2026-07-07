#!/usr/bin/env python3
"""
Download lecture/tutorial resource files from all Moodle courses
into /home/colin/Unsw/{COURSE}/{Lectures|Tutorials|Assignments|Materials}/
Uses the existing Chromium CDP session (http://127.0.0.1:9222).
Idempotent — skips files that already exist.
"""
import asyncio, html, json, os, re, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright

CDP_URL = "http://127.0.0.1:9222"
BASE = "https://moodle.telt.unsw.edu.au"
OUT_ROOT = Path("/home/colin/Unsw")
REPORT_PATH = Path("/tmp/moodle_resource_download_report.json")

COURSES = {
    "COMP9511": "96757",
    "COMP9414": "96758",
    "COMP9417": "96559",
    "GSOE9011": "96676",
    "GSOE9820": "94448",
}

ALLOWED_EXTS = {
    ".pdf", ".pptx", ".ppt", ".pptm",
    ".docx", ".doc",
    ".zip", ".tar", ".gz", ".7z",
    ".ipynb", ".py",
    ".csv", ".xlsx", ".xls",
    ".txt", ".md",
}

PLUGINFILE_RE = re.compile(r"https://moodle\.telt\.unsw\.edu\.au/pluginfile\.php[^\"\'\s>]+", re.I)


def sanitize(name: str, max_len: int = 180) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", (name or "").strip())
    name = re.sub(r"\s+", " ", name).strip()
    return name[:max_len] or "file"


def ext_of(url: str) -> str:
    return Path(urlparse(url).path).suffix.lower()


def fname_from_url(url: str) -> str:
    base = os.path.basename(urlparse(url).path) or "resource"
    return sanitize(base)


def infer_category(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["assignment", "homework", "rubric", "project", "submission", "ass "]):
        return "Assignments"
    if any(k in t for k in ["tutorial", "tut ", "lab ", "lab0", "exercise", "worksheet", "practical"]):
        return "Tutorials"
    return "Lectures"


async def resolve_resource(ctx, url: str) -> str:
    """Resolve mod/resource/view.php to a downloadable pluginfile URL."""
    try:
        resp = await ctx.request.get(url, timeout=45000)
        ctype = (resp.headers.get("content-type") or "").lower()
        raw = await resp.text()
        # If the resource itself is already a file (direct download / inline)
        if resp.ok and any(e in ctype for e in ["pdf", "zip", "octet", "powerpoint", "msword", "vnd.ms", "notebook"]):
            return url
        # Extract pluginfile URL from response body
        hits = PLUGINFILE_RE.findall(raw)
        if hits:
            return html.unescape(hits[0])
    except Exception:
        pass
    return ""


async def collect_folder_files(ctx, page, folder_url: str) -> list[str]:
    """Navigate to a mod/folder page and collect all downloadable file links."""
    out = []
    try:
        await page.goto(folder_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(1000)
        links = await page.evaluate('''() => {
            const out = [];
            const seen = new Set();
            for (const a of document.querySelectorAll("a[href]")) {
                const href = a.href;
                if (!href || seen.has(href)) continue;
                seen.add(href);
                out.push(href);
            }
            return out;
        }''')
        for href in links:
            hl = href.lower()
            e = ext_of(href)
            if "pluginfile.php" in hl or e in ALLOWED_EXTS:
                out.append(href)
    except Exception:
        pass
    return out


async def download_file(ctx, url: str, out_path: Path) -> bool:
    try:
        resp = await ctx.request.get(url, timeout=120000)
        if not resp.ok:
            return False
        data = await resp.body()
        if len(data) < 100:
            return False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        return True
    except Exception:
        return False


async def main():
    report = {
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "downloaded": [],
        "skipped_existing": 0,
        "errors": [],
    }

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]
        page = await ctx.new_page()

        # Verify logged in
        await page.goto(f"{BASE}/my/", wait_until="domcontentloaded", timeout=45000)
        if "log in" in (await page.title()).lower():
            raise RuntimeError("Moodle session expired — re-inject cookies first")

        for code, cid in COURSES.items():
            course_url = f"{BASE}/course/view.php?id={cid}"
            print(f"\n=== {code} (id={cid}) ===")
            try:
                await page.goto(course_url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(1500)
            except Exception as e:
                report["errors"].append(f"{code}: failed to open course page: {e}")
                continue

            links = await page.evaluate('''() => {
                const out = [];
                const seen = new Set();
                for (const a of document.querySelectorAll("a[href]")) {
                    const href = a.href;
                    const text = (a.textContent||"").replace(/\\s+/g," ").trim();
                    if (!href || seen.has(href)) continue;
                    seen.add(href);
                    out.push({href, text});
                }
                return out;
            }''')

            candidates = []
            folder_links = []
            for l in links:
                href, txt = l["href"], l.get("text", "")
                hl = href.lower()
                e = ext_of(href)
                if "mod/resource/view.php" in hl or "pluginfile.php" in hl or e in ALLOWED_EXTS:
                    candidates.append((href, txt, infer_category(txt)))
                elif "mod/folder/view.php" in hl:
                    folder_links.append((href, txt, infer_category(txt)))

            # Recurse into folders
            for furl, ftxt, fcat in folder_links:
                print(f"  folder: {ftxt!r}")
                files = await collect_folder_files(ctx, page, furl)
                for fhref in files:
                    candidates.append((fhref, ftxt, fcat))
                # return to course page
                try:
                    await page.goto(course_url, wait_until="domcontentloaded", timeout=45000)
                    await page.wait_for_timeout(500)
                except Exception:
                    pass

            # Deduplicate by href
            seen_hrefs = {}
            for href, txt, cat in candidates:
                if href not in seen_hrefs:
                    seen_hrefs[href] = (txt, cat)

            print(f"  {len(seen_hrefs)} candidate resources")

            for href, (txt, cat) in seen_hrefs.items():
                raw_url = urljoin(BASE, href)
                final_url = raw_url

                # Resolve resource-view pages
                if "mod/resource/view.php" in raw_url:
                    resolved = await resolve_resource(ctx, raw_url)
                    if not resolved:
                        report["errors"].append(f"{code}: resolve failed for {txt!r}")
                        continue
                    final_url = resolved

                e = ext_of(final_url)
                if e not in ALLOWED_EXTS and "pluginfile.php" not in final_url.lower():
                    # Maybe the resolved URL reveals the ext
                    if not any(ext in final_url.lower() for ext in ALLOWED_EXTS):
                        report["errors"].append(f"{code}: unrecognised type {e!r} for {txt!r}")
                        continue

                # Re-infer category if we now have a better name from the link text
                fname = sanitize(txt) if txt and len(txt) > 3 else fname_from_url(final_url)
                # Add extension if missing
                if e in ALLOWED_EXTS and not fname.lower().endswith(e):
                    fname = fname + e
                elif not Path(fname).suffix:
                    fe = ext_of(final_url)
                    if fe in ALLOWED_EXTS:
                        fname = fname + fe

                out_path = OUT_ROOT / code / cat / fname
                if out_path.exists():
                    report["skipped_existing"] += 1
                    continue

                ok = await download_file(ctx, final_url, out_path)
                if ok:
                    size = out_path.stat().st_size
                    report["downloaded"].append({
                        "course": code,
                        "category": cat,
                        "file": str(out_path),
                        "size": size,
                        "source": final_url[:200],
                    })
                    print(f"  DL {cat}/{fname} ({size//1024}KB)")
                else:
                    report["errors"].append(f"{code}: download failed for {txt!r}")

        await page.close()
        await browser.close()

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    total_size = sum(it["size"] for it in report["downloaded"])
    print(f"\n=== DONE: downloaded={len(report['downloaded'])} skipped={report['skipped_existing']} errors={len(report['errors'])} total_size={total_size//1024//1024}MB ===")


if __name__ == "__main__":
    asyncio.run(main())
