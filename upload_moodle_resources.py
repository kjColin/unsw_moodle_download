#!/usr/bin/env python3
"""
Upload all files in /home/colin/Unsw/{COURSE}/{category}/ to Baidu Netdisk
at /Unsw/{COURSE}/{category}/{filename}, verify, then delete local copy.
Tracks state in /home/colin/moodle_resource_registry.json.
"""
import fcntl, json, os, subprocess, time
from contextlib import contextmanager
from pathlib import Path

LOCAL_ROOT = Path("/home/colin/Unsw")
REMOTE_ROOT = "/Unsw"
REGISTRY = Path("/home/colin/moodle_resource_registry.json")
LOCK_PATH = Path("/home/colin/moodle_resource_registry.lock")
BAIDU_BIN = "/home/colin/.local/bin/BaiduPCS-Go"

# Only upload files from these courses/directories
COURSES = {"COMP9511", "COMP9414", "COMP9417", "GSOE9011", "GSOE9820", "Summaries"}

# Whitelist — only upload recognised study materials, nothing from venvs/caches
UPLOAD_EXTS = {
    ".pdf", ".pptx", ".ppt", ".pptm",
    ".docx", ".doc",
    ".zip", ".tar", ".gz", ".7z",
    ".ipynb",
    ".csv", ".xlsx", ".xls",
    ".txt", ".md",
    ".py",   # standalone scripts, not venv packages
}
# Skip files inside virtual-environment or Python-package directories
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


def in_skip_dir(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def collect_files():
    files = []
    for course in COURSES:
        course_dir = LOCAL_ROOT / course
        if not course_dir.is_dir():
            continue
        for path in sorted(course_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            if path.suffix.lower() not in UPLOAD_EXTS:
                continue
            if in_skip_dir(path):
                continue
            # derive remote dir mirroring local structure
            rel = path.relative_to(LOCAL_ROOT)
            parts = list(rel.parts)
            remote_dir = REMOTE_ROOT + "/" + "/".join(parts[:-1])
            files.append((path, remote_dir))
    return files


def main():
    files = collect_files()
    data = load_reg()
    already_uploaded = sum(1 for v in data["items"].values() if v.get("uploaded"))
    todo = [
        (p, rd) for p, rd in files
        if not data["items"].get(str(p), {}).get("uploaded")
    ]
    print(f"TOTAL_FILES={len(files)}  ALREADY_UPLOADED={already_uploaded}  TODO={len(todo)}")

    ok, fail = 0, 0
    for local_path, remote_dir in todo:
        key = str(local_path)
        if not local_path.exists():
            continue
        size = local_path.stat().st_size
        fname = local_path.name
        print(f"--- UPLOAD {local_path.parent.name}/{fname} ({human(size)}) -> {remote_dir}")
        update_item(key, upload_status="uploading", local_path=key, remote_dir=remote_dir)
        baidu_mkdir(remote_dir)
        rc, out, err = baidu_upload(local_path, remote_dir)
        if rc != 0:
            print(f"  UPLOAD_FAILED rc={rc}")
            print(err[-500:])
            update_item(key, upload_status="failed")
            fail += 1
            continue
        line = baidu_ls(remote_dir, fname)
        if not line:
            print("  VERIFY_FAILED: not found on remote")
            update_item(key, upload_status="verify_failed")
            fail += 1
            continue
        print(f"  VERIFIED: {line[:100]}")
        update_item(key, uploaded=True, upload_status="done")
        try:
            os.remove(local_path)
            print(f"  LOCAL_DELETED: {local_path}")
            update_item(key, local_deleted=True)
            # Remove empty parent dirs
            for parent in [local_path.parent, local_path.parent.parent]:
                try:
                    if parent.is_dir() and not any(parent.iterdir()):
                        parent.rmdir()
                except Exception:
                    pass
        except Exception as e:
            print(f"  DELETE_FAILED: {e}")
        ok += 1
        print(f"  [{ok} ok / {fail} fail / {len(todo)} total]")

    print(f"\nSUMMARY ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
