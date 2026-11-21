#!/usr/bin/env python3
"""
Download course materials that live on WebCMS3 rather than Moodle
(COMP6714 keeps its slides there) into /home/colin/Unsw/<course>/<category>/,
where upload_moodle_resources.py picks them up for the Baidu + Drive backup.

Uses the logged-in 9222 browser over CDP, like the Moodle scripts: WebCMS
returns 403 to anonymous requests.

What a WebCMS resource page can hold, and what we keep of it:
  /files/<hash>/attachment     uploaded file (slides, sample exam)  -> saved as-is
  iframe to a *.cse.unsw.edu.au page (project spec)                 -> saved as .html
  link to github.com/<org>/<repo>/tree/<branch>                     -> <repo>-<sha7>.zip
Pages that only point back to Moodle (lecture videos, the Moodle-hosted
assignment) hold nothing to fetch; recordings are backed up from Echo360.

Re-runnable. /home/colin/webcms_manifest.json remembers which file hash went
to which local path, so nothing is fetched twice and two different files that
share a name don't overwrite each other.
"""
import asyncio, json, os, re, sys, urllib.request
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

CDP = "http://127.0.0.1:9222"
BASE = "https://webcms3.cse.unsw.edu.au"
LOCAL_ROOT = Path("/home/colin/Unsw")
MANIFEST = Path("/home/colin/webcms_manifest.json")

# course -> (offering, {local category dir: WebCMS resource-list id})
COURSES = {
    "COMP6714": ("26T3", {"Lectures": 124367, "Assignments": 124372, "Exercises": 124370}),
}

FILE_RE = re.compile(r"^https://webcms3\.cse\.unsw\.edu\.au/files/([0-9a-f]{32,})$")
GITHUB_TREE_RE = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/tree/([\w.-]+)/?$")
UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_name(name):
    name = UNSAFE.sub("_", name).strip(" .")
    return name[:180] or "file"


def load_manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


def save_manifest(m):
    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, MANIFEST)


def target_path(cat_dir: Path, name: str, key: str, manifest) -> Path:
    """Where `key` goes. A name already taken by a different key gets a suffix."""
    if key in manifest:
        return Path(manifest[key])
    p = cat_dir / safe_name(name)
    taken = {v for k, v in manifest.items() if k != key}
    if str(p) in taken:
        p = p.with_name(f"{p.stem}_{key[-8:]}{p.suffix}")
    return p


def write_atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


async def logged_in(page):
    return await page.evaluate(
        """() => !!document.querySelector('a[href*="/users/"][href$="/settings"]')""")


async def page_links(page):
    return await page.evaluate("""() => ({
        anchors: Array.from(document.querySelectorAll('a[href]'))
                 .map(a => [a.textContent.trim().replace(/\\s+/g, ' '), a.href]),
        frames:  Array.from(document.querySelectorAll('iframe[src]')).map(f => f.src),
    })""")


def leaf_ids(anchors, course, offering, list_ids):
    pat = re.compile(rf"^{re.escape(BASE)}/{course}/{offering}/resources/(\d+)$")
    seen = []
    for _text, href in anchors:
        m = pat.match(href)
        if m and int(m.group(1)) not in list_ids and int(m.group(1)) not in seen:
            seen.append(int(m.group(1)))
    return seen


def fetchables(anchors, frames):
    """[(key, filename, url, kind)] found on one page."""
    out = {}
    for text, href in anchors:
        m = FILE_RE.match(href)
        # The file's own name is the text of the plain /files/<hash> link;
        # "View in browser" points at the same URL.
        if m and text and text != "View in browser":
            out[m.group(1)] = (m.group(1), text, href + "/attachment", "file")
        g = GITHUB_TREE_RE.match(href)
        if g:
            out[href] = (href, None, href, "github")
    for src in frames:
        u = urlparse(src)
        if u.hostname and u.hostname.endswith("cse.unsw.edu.au") and "webcms3" not in u.hostname:
            segs = [s.lstrip("~") for s in u.path.split("/") if s]
            name = segs[-1] if segs else "index.html"
            if not name.endswith((".html", ".htm")):
                name += ".html"
            if name in ("index.html", "index.htm"):
                # .../~cs6714/21T3/index.html -> cs6714-21T3-index.html
                name = "-".join(segs[:-1] + [name]) if len(segs) > 1 else name
            out[src] = (src, name, src, "html")
    return list(out.values())


def github_zip(org, repo, branch):
    """(sha7, zip bytes) of a public repo branch; the sha in the name means
    a later push lands as a new file instead of silently not being re-fetched."""
    req = urllib.request.Request(f"https://api.github.com/repos/{org}/{repo}/commits/{branch}",
                                 headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        sha = json.load(r)["sha"][:7]
    with urllib.request.urlopen(f"https://codeload.github.com/{org}/{repo}/zip/refs/heads/{branch}",
                                timeout=300) as r:
        return sha, r.read()


async def run():
    manifest = load_manifest()
    got = skipped = failed = 0
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        try:
            for course, (offering, lists) in COURSES.items():
                list_ids = set(lists.values())
                for category, list_id in lists.items():
                    cat_dir = LOCAL_ROOT / course / category
                    url = f"{BASE}/{course}/{offering}/resources/{list_id}"
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    if (resp and resp.status == 403) or not await logged_in(page):
                        raise RuntimeError("WebCMS login expired on CDP browser")
                    links = await page_links(page)
                    found = fetchables(links["anchors"], links["frames"])
                    for rid in leaf_ids(links["anchors"], course, offering, list_ids):
                        await page.goto(f"{BASE}/{course}/{offering}/resources/{rid}",
                                        wait_until="domcontentloaded", timeout=60000)
                        leaf = await page_links(page)
                        found += fetchables(leaf["anchors"], leaf["frames"])

                    done_keys = set()
                    for key, name, src, kind in found:
                        if key in done_keys:
                            continue
                        done_keys.add(key)
                        if key in manifest and Path(manifest[key]).exists():
                            skipped += 1
                            continue
                        try:
                            if kind == "github":
                                org, repo, branch = GITHUB_TREE_RE.match(src).groups()
                                sha, data = github_zip(org, repo, branch)
                                key = f"{src}@{sha}"
                                if key in manifest and Path(manifest[key]).exists():
                                    skipped += 1
                                    continue
                                name = f"{repo}-{sha}.zip"
                            else:
                                r = await ctx.request.get(src, timeout=300000)
                                if not r.ok:
                                    raise RuntimeError(f"HTTP {r.status}")
                                data = await r.body()
                                if name.lower().endswith(".pdf") and not data.startswith(b"%PDF"):
                                    raise RuntimeError("not a PDF (login page?)")
                            path = target_path(cat_dir, name, key, manifest)
                            write_atomic(path, data)
                            manifest[key] = str(path)
                            save_manifest(manifest)
                            got += 1
                            print(f"GOT {course}/{category}/{path.name} ({len(data)//1024} KB)", flush=True)
                        except Exception as e:
                            failed += 1
                            print(f"FAILED {course}/{category} {name or src}: {e}", flush=True)
        finally:
            await page.close()
    print(f"SUMMARY got={got} skipped={skipped} failed={failed}", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
