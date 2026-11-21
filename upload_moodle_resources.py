#!/usr/bin/env python3
"""
Back up course materials under /home/colin/Unsw to BOTH Baidu Netdisk and
Google Drive, verifying each. Local copies are kept.

  Baidu:  /Unsw/<rel dir>/<file>                       (unchanged layout)
  Drive:  UNSW-Backup/<term>/<course>/<rel dir>/<file>
          UNSW-Backup/<term>/<course>/Summaries/...    (for Summaries/<course>/...)

Why local copies stay: moodle_extract_pdfs_cdp.py decides what to download by
whether the file already exists locally. Deleting after upload (the old
behaviour) made every daily run fetch the same materials again — the T1 files
that came back on 2026-09-17 were exactly that. Materials are tens of MB a
term, so keeping them costs nothing; videos are the ones worth deleting.

Courses are discovered from disk rather than listed: a hard-coded set is why
no T3 material was ever uploaded.

State lives in /home/colin/moodle_resource_registry.json, keyed by local path.
"""
import fcntl, json, os, subprocess, sys, time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from upload_and_clean_videos import (  # noqa: E402  (shared Drive plumbing + term map)
    GDRIVE_BASE, gdrive_available, gdrive_remote_size, gdrive_upload, term_for,
)

LOCAL_ROOT = Path("/home/colin/Unsw")
REMOTE_ROOT = "/Unsw"
REGISTRY = Path("/home/colin/moodle_resource_registry.json")
LOCK_PATH = Path("/home/colin/moodle_resource_registry.lock")
BAIDU_BIN = "/home/colin/.local/bin/BaiduPCS-Go"
SUMMARIES = "Summaries"

# Whitelist — only recognised study materials, nothing from venvs/caches.
# Videos are deliberately absent: they go through upload_and_clean_videos.py.
UPLOAD_EXTS = {
    ".pdf", ".pptx", ".ppt", ".pptm",
    ".docx", ".doc",
    ".zip", ".tar", ".gz", ".7z",
    ".ipynb",
    ".csv", ".xlsx", ".xls",
    ".txt", ".md",
    ".py",
}
SKIP_DIRS = {".venv", "venv", "site-packages", "__pycache__", ".git", "node_modules"}


@contextmanager
def reg_lock():
    with open(LOCK_PATH, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def load_reg():
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {"version": 1, "items": {}}


def save_reg(data):
    tmp = REGISTRY.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, REGISTRY)


def update_item(key, **fields):
    with reg_lock():
        data = load_reg()
        item = data["items"].setdefault(key, {})
        item.update(fields)
        item["updated_at"] = int(time.time())
        save_reg(data)


def human(n):
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def needs_upload(item):
    return not (item.get("uploaded") and item.get("gdrive_uploaded"))


def baidu_dir_for(rel_dir_parts):
    return REMOTE_ROOT + "/" + "/".join(rel_dir_parts)


def gdrive_dir_for(rel_dir_parts):
    parts = list(rel_dir_parts)
    if parts and parts[0] == SUMMARIES:
        if len(parts) == 1:
            return f"{GDRIVE_BASE}/{SUMMARIES}"
        course, rest = parts[1], parts[2:]
        return "/".join([GDRIVE_BASE, term_for(course), course, SUMMARIES] + rest)
    course, rest = parts[0], parts[1:]
    return "/".join([GDRIVE_BASE, term_for(course), course] + rest)


def in_skip_dir(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def collect_files(root: Path = LOCAL_ROOT):
    """(path, rel_dir_parts) for every uploadable file, across every course dir."""
    out = []
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in UPLOAD_EXTS:
            continue
        rel = path.relative_to(root)
        if in_skip_dir(rel) or len(rel.parts) < 2:
            continue
        out.append((path, tuple(rel.parts[:-1])))
    return out


def baidu_mkdir(remote_dir):
    subprocess.run([BAIDU_BIN, "mkdir", remote_dir], capture_output=True, text=True)


def baidu_upload(local_path, remote_dir):
    r = subprocess.run(
        [BAIDU_BIN, "upload", "--policy=overwrite", str(local_path), remote_dir],
        capture_output=True, text=True, timeout=3600,
    )
    return r.returncode, r.stdout, r.stderr


def baidu_ls(remote_dir, filename):
    r = subprocess.run([BAIDU_BIN, "ls", remote_dir], capture_output=True, text=True, timeout=60)
    for line in r.stdout.splitlines():
        if filename in line:
            return line.strip()
    return None


def push_baidu(key, item, path, rel_dir):
    if item.get("uploaded"):
        return True
    remote_dir = baidu_dir_for(rel_dir)
    baidu_mkdir(remote_dir)
    rc, _out, err = baidu_upload(path, remote_dir)
    if rc != 0:
        print(f"  BAIDU_FAILED rc={rc} {err[-300:]}")
        update_item(key, upload_status="failed")
        return False
    if not baidu_ls(remote_dir, path.name):
        print("  BAIDU_VERIFY_FAILED")
        update_item(key, upload_status="verify_failed")
        return False
    update_item(key, uploaded=True, upload_status="done", remote_dir=remote_dir)
    return True


def push_gdrive(key, item, path, rel_dir):
    if item.get("gdrive_uploaded"):
        return True
    gdir = gdrive_dir_for(rel_dir)
    rc, _out, err = gdrive_upload(str(path), gdir)
    if rc != 0:
        print(f"  GDRIVE_FAILED rc={rc} {err[-300:]}")
        update_item(key, gdrive_status=f"failed_rc_{rc}")
        return False
    remote = gdrive_remote_size(gdir, path.name)
    local = path.stat().st_size
    if remote != local:
        print(f"  GDRIVE_VERIFY_FAILED remote={remote} local={local}")
        update_item(key, gdrive_status="verify_failed")
        return False
    update_item(key, gdrive_uploaded=True, gdrive_status="done", gdrive_dir=gdir)
    return True


def main():
    ok_drive, why = gdrive_available()
    if not ok_drive:
        print(f"GDRIVE_UNAVAILABLE: {why}")
        return 2

    files = collect_files()
    items = load_reg()["items"]
    todo = [(p, rd) for p, rd in files if needs_upload(items.get(str(p), {}))]
    print(f"TOTAL_FILES={len(files)}  TODO={len(todo)}")

    ok = fail = 0
    for path, rel_dir in todo:
        key = str(path)
        item = load_reg()["items"].get(key, {})
        print(f"--- {'/'.join(rel_dir)}/{path.name} ({human(path.stat().st_size)})")
        update_item(key, local_path=key)
        b = push_baidu(key, item, path, rel_dir)
        g = push_gdrive(key, item, path, rel_dir)
        if b and g:
            ok += 1
        else:
            fail += 1
    print(f"SUMMARY ok={ok} fail={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
