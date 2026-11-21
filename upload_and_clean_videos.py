#!/usr/bin/env python3
"""Roll through video_sync_registry.json: upload downloaded videos to BOTH
Baidu Netdisk and Google Drive, verify each, then delete the local copy once
both remotes hold it — so a failure on either side never loses the only copy."""
import fcntl, json, os, subprocess, sys, time
from contextlib import contextmanager
from pathlib import Path

LOCAL_REG = Path('/home/colin/video_sync_registry.json')
LOCK_PATH = Path('/home/colin/video_sync_registry.lock')
BAIDU_BIN = '/home/colin/.local/bin/BaiduPCS-Go'
REMOTE_BASE = '/Unsw'
RCLONE_BIN = 'rclone'
GDRIVE_REMOTE = 'gdrive'
GDRIVE_BASE = 'UNSW-Backup'
# Drive groups by term as well as course; Baidu deliberately does not (its 400+
# existing files would all have to be moved). Courses missing from the map land
# in Unsorted rather than failing the upload.
COURSE_TERMS = Path('/home/colin/video_pipeline/course_terms.json')
UNKNOWN_TERM = 'Unsorted'
# Drive accepts the file but may still be settling; sizes must match exactly.
SIZE_TOLERANCE = 0

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

def term_for(course_name):
    try:
        return json.loads(COURSE_TERMS.read_text(encoding='utf-8')).get(course_name) or UNKNOWN_TERM
    except Exception:
        return UNKNOWN_TERM

def gdrive_dir_for(course_name):
    return f'{GDRIVE_BASE}/{term_for(course_name)}/{course_name}/Lectures'

def needs_work(it):
    """True while this item still owes an upload to either remote."""
    if not it.get('downloaded'):
        return False
    return not (it.get('uploaded') and it.get('gdrive_uploaded'))

def safe_to_delete_local(it):
    """The one rule that protects the only local copy: both remotes verified.
    Items from before Drive existed carry no gdrive_uploaded, so they fail
    this check and wait to be mirrored instead of being deleted."""
    return bool(it.get('uploaded')) and bool(it.get('gdrive_uploaded'))

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

def gdrive_available():
    """A missing/unconfigured remote must not look like an upload failure —
    it means Drive was never set up, so say so once and leave files alone."""
    r = subprocess.run([RCLONE_BIN, 'listremotes'], capture_output=True, text=True)
    if r.returncode != 0:
        return False, 'rclone not runnable'
    if f'{GDRIVE_REMOTE}:' not in r.stdout.split():
        return False, f'remote "{GDRIVE_REMOTE}:" not configured (run rclone config)'
    return True, ''

def gdrive_upload(local_path, gdrive_dir):
    dest = f'{GDRIVE_REMOTE}:{gdrive_dir}/{os.path.basename(local_path)}'
    r = subprocess.run([RCLONE_BIN, 'copyto', local_path, dest,
                        '--drive-chunk-size', '64M', '--retries', '3', '--low-level-retries', '10'],
                       capture_output=True, text=True, timeout=7200)
    return r.returncode, r.stdout, r.stderr

def gdrive_remote_size(gdrive_dir, filename):
    """Byte size of the remote copy, or None if it isn't there."""
    dest = f'{GDRIVE_REMOTE}:{gdrive_dir}/{filename}'
    r = subprocess.run([RCLONE_BIN, 'lsjson', dest], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        return None
    try:
        entries = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    for e in entries:
        if e.get('Name') == filename:
            return e.get('Size')
    return None

def human(n):
    for unit in ['B','KB','MB','GB']:
        if n < 1024: return f'{n:.2f}{unit}'
        n /= 1024
    return f'{n:.2f}TB'

def push_to_baidu(it, local_path, course, fname):
    """Upload + verify on Baidu. Returns True once the registry says done."""
    if it.get('uploaded'):
        return True
    remote_dir = remote_dir_for(course)
    baidu_mkdir(remote_dir)
    print(f'--- BAIDU [{course}] {fname} -> {remote_dir}')
    update_item(it['dedup_key'], upload_status='uploading')
    rc, out, err = baidu_upload(local_path, remote_dir)
    if rc != 0:
        print('BAIDU_UPLOAD_FAILED rc=', rc)
        print(err[-1000:])
        update_item(it['dedup_key'], upload_status='failed', note=f'upload_rc_{rc}')
        return False
    line = baidu_remote_size(remote_dir, fname)
    if not line:
        print('BAIDU_VERIFY_FAILED: file not found on remote listing')
        update_item(it['dedup_key'], upload_status='verify_failed')
        return False
    print('BAIDU_VERIFIED:', line.strip()[:140])
    update_item(it['dedup_key'], uploaded=True, upload_status='done',
                remote_dir=remote_dir, note='uploaded_and_verified')
    return True

def push_to_gdrive(it, local_path, course, fname, local_size):
    """Upload + size-verify on Drive. Returns True once the registry says done."""
    if it.get('gdrive_uploaded'):
        return True
    gdir = gdrive_dir_for(course)
    print(f'--- GDRIVE [{course}] {fname} -> {GDRIVE_REMOTE}:{gdir}')
    update_item(it['dedup_key'], gdrive_status='uploading')
    rc, out, err = gdrive_upload(local_path, gdir)
    if rc != 0:
        print('GDRIVE_UPLOAD_FAILED rc=', rc)
        print(err[-1000:])
        update_item(it['dedup_key'], gdrive_status=f'failed_rc_{rc}')
        return False
    remote_size = gdrive_remote_size(gdir, fname)
    if remote_size is None:
        print('GDRIVE_VERIFY_FAILED: not present after upload')
        update_item(it['dedup_key'], gdrive_status='verify_failed')
        return False
    if abs(remote_size - local_size) > SIZE_TOLERANCE:
        print(f'GDRIVE_VERIFY_FAILED: size {remote_size} != local {local_size}')
        update_item(it['dedup_key'], gdrive_status='size_mismatch')
        return False
    print(f'GDRIVE_VERIFIED: {human(remote_size)}')
    update_item(it['dedup_key'], gdrive_uploaded=True, gdrive_status='done', gdrive_dir=gdir)
    return True

def main():
    gdrive_ok, gdrive_why = gdrive_available()
    if not gdrive_ok:
        print(f'GDRIVE_UNAVAILABLE: {gdrive_why}')
        print('Refusing to run: Baidu-only uploads would strand files that can '
              'never be cleaned up. Configure Drive first.')
        return 2

    data = load_reg()
    items = data.get('items', [])
    todo = [it for it in items if needs_work(it) and os.path.exists(it.get('local_path', ''))]
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
        print(f'=== [{course}] {fname} ({human(size)})')

        baidu_done = push_to_baidu(it, local_path, course, fname)
        gdrive_done = push_to_gdrive(it, local_path, course, fname, size)

        if not (baidu_done and gdrive_done):
            print(f'KEEPING_LOCAL (baidu={baidu_done} gdrive={gdrive_done}) — retried next pass')
            fail += 1
            continue

        # Both remotes verified: this is the only point where the local copy goes.
        fresh = next((x for x in load_reg().get('items', []) if x.get('dedup_key') == dedup_key), {})
        if not safe_to_delete_local(fresh):
            print('KEEPING_LOCAL: registry does not confirm both remotes')
            fail += 1
            continue
        try:
            os.remove(local_path)
            print('LOCAL_DELETED:', local_path)
            update_item(dedup_key, local_deleted=True)
        except Exception as e:
            print('LOCAL_DELETE_FAILED:', e)
        ok += 1
        print(f'DONE [{ok} ok / {fail} fail / {len(todo)} total]')

    print(f'SUMMARY ok={ok} fail={fail}')
    return 0

if __name__ == '__main__':
    sys.exit(main() or 0)
