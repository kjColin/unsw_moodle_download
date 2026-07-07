#!/usr/bin/env python3
"""Roll through video_sync_registry.json: upload downloaded-but-not-uploaded
videos to Baidu Netdisk, verify, then delete the local copy to save disk space."""
import fcntl, json, os, subprocess, sys, time
from contextlib import contextmanager
from pathlib import Path

LOCAL_REG = Path('/home/colin/video_sync_registry.json')
LOCK_PATH = Path('/home/colin/video_sync_registry.lock')
BAIDU_BIN = '/home/colin/.local/bin/BaiduPCS-Go'
REMOTE_BASE = '/Unsw'

@contextmanager
def reg_lock():
    """Same lock file as echo360_batch_download.py — lets download and upload
    run concurrently while serializing their registry read-modify-write cycles."""
    with open(LOCK_PATH, 'w') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def load_reg():
    return json.loads(LOCAL_REG.read_text(encoding='utf-8'))

def save_reg(data):
    tmp = LOCAL_REG.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, LOCAL_REG)

def update_item(dedup_key, **fields):
    """Re-reads the registry fresh, patches just one item, writes back —
    all under the lock — so a concurrent downloader's new entries are never
    overwritten by a stale in-memory copy (the original lost-update bug)."""
    with reg_lock():
        data = load_reg()
        for it in data.get('items', []):
            if it.get('dedup_key') == dedup_key:
                it.update(fields)
                it['updated_at'] = int(time.time())
                break
        save_reg(data)
        return data

def remote_dir_for(course_name):
    return f'{REMOTE_BASE}/{course_name}/Lectures'

def baidu_mkdir(remote_dir):
    subprocess.run([BAIDU_BIN, 'mkdir', remote_dir], capture_output=True, text=True)

def baidu_upload(local_path, remote_dir):
    r = subprocess.run([BAIDU_BIN, 'upload', '--policy=overwrite', local_path, remote_dir],
                       capture_output=True, text=True, timeout=3600)
    return r.returncode, r.stdout, r.stderr

def baidu_remote_size(remote_dir, filename):
    r = subprocess.run([BAIDU_BIN, 'ls', remote_dir], capture_output=True, text=True, timeout=120)
    for line in r.stdout.splitlines():
        if filename in line:
            return line
    return None

def human(n):
    for unit in ['B','KB','MB','GB']:
        if n < 1024: return f'{n:.2f}{unit}'
        n /= 1024
    return f'{n:.2f}TB'

def main():
    data = load_reg()
    items = data.get('items', [])
    todo = [it for it in items if it.get('downloaded') and not it.get('uploaded') and os.path.exists(it.get('local_path',''))]
    print(f'TOTAL_PENDING_UPLOAD={len(todo)}')

    ok, fail = 0, 0
    for it in todo:
        dedup_key = it['dedup_key']
        local_path = it['local_path']
        course = it.get('course_name', 'UNKNOWN')
        fname = os.path.basename(local_path)
        if not os.path.exists(local_path):
            continue  # a concurrent run may have already uploaded+deleted this one
        size = os.path.getsize(local_path)
        remote_dir = remote_dir_for(course)
        baidu_mkdir(remote_dir)
        print(f'--- UPLOAD [{course}] {fname} ({human(size)}) -> {remote_dir}')
        update_item(dedup_key, upload_status='uploading')
        rc, out, err = baidu_upload(local_path, remote_dir)
        if rc != 0:
            print('UPLOAD_FAILED rc=', rc)
            print(err[-1000:])
            update_item(dedup_key, upload_status='failed', note=f'upload_rc_{rc}')
            fail += 1
            continue
        # verify on remote
        line = baidu_remote_size(remote_dir, fname)
        if not line:
            print('VERIFY_FAILED: file not found on remote listing')
            update_item(dedup_key, upload_status='verify_failed')
            fail += 1
            continue
        print('VERIFIED_ON_REMOTE:', line.strip()[:140])
        update_item(dedup_key, uploaded=True, upload_status='done',
                    remote_dir=remote_dir, note='uploaded_and_verified')
        # delete local copy now that it's safely on the netdisk — finishes this
        # video's lifecycle (download -> upload -> verify -> clean) immediately,
        # independent of any other video's progress
        try:
            os.remove(local_path)
            print('LOCAL_DELETED:', local_path)
            update_item(dedup_key, local_deleted=True)
        except Exception as e:
            print('LOCAL_DELETE_FAILED:', e)
        ok += 1
        print(f'DONE [{ok} ok / {fail} fail / {len(todo)} total]')

    print(f'SUMMARY ok={ok} fail={fail}')

if __name__ == '__main__':
    main()
