#!/usr/bin/env python3
"""Bring back course materials that exist only on Baidu, so they can be
mirrored to Google Drive by upload_moodle_resources.py.

Until 2026-11 the materials uploader deleted each local file once it was on
Baidu, so the June uploads of T1 materials survive only there. This fetches
each one back to its original local path (taken from the registry key) and
leaves it in place — the uploader then sees it as on Baidu but missing from
Drive and uploads it to Drive only.

Baidu throttles this account to roughly 0.2 MB/s, which is fine for a few
hundred MB of PDFs. Re-runnable: files already back on disk are skipped.
"""
import json, os, subprocess, sys
from pathlib import Path

REGISTRY = Path("/home/colin/moodle_resource_registry.json")
BAIDU_BIN = "/home/colin/.local/bin/BaiduPCS-Go"


def wanted():
    items = json.loads(REGISTRY.read_text(encoding="utf-8"))["items"]
    for key, v in sorted(items.items()):
        if v.get("uploaded") and not v.get("gdrive_uploaded") and v.get("remote_dir") \
                and not os.path.exists(key):
            yield Path(key), v["remote_dir"]


def main():
    todo = list(wanted())
    print(f"TO_RESTORE={len(todo)}", flush=True)
    ok = fail = 0
    for local, remote_dir in todo:
        local.parent.mkdir(parents=True, exist_ok=True)
        remote = f"{remote_dir}/{local.name}"
        r = subprocess.run([BAIDU_BIN, "download", remote, "--saveto", str(local.parent)],
                           capture_output=True, text=True, timeout=3600)
        if r.returncode == 0 and local.exists():
            ok += 1
            print(f"RESTORED [{ok}/{len(todo)}] {local.relative_to('/home/colin/Unsw')}", flush=True)
        else:
            fail += 1
            tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or ['']
            print(f"RESTORE_FAILED {remote} :: {tail[0][:160]}", flush=True)
    print(f"SUMMARY restored={ok} failed={fail}", flush=True)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
