import asyncio, fcntl, json, os, re, subprocess, sys, time
from contextlib import contextmanager
from pathlib import Path
from playwright.async_api import async_playwright

CDP = 'http://127.0.0.1:9222'
REG_PATH = Path('/home/colin/video_sync_registry.json')
LOCK_PATH = Path('/home/colin/video_sync_registry.lock')

@contextmanager
def reg_lock():
    """Exclusive lock spanning a full load-modify-save cycle, so the download
    and upload pipelines can run concurrently without clobbering each other's
    registry updates (lost-update race condition)."""
    with open(LOCK_PATH, 'w') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

COOKIE_NAMES = {
    'CloudFront-Key-Pair-Id', 'CloudFront-Policy', 'CloudFront-Signature',
    'ECHO_JWT', 'PLAY_SESSION', 'CloudFront-Tracking2'
}

# Echo360 lectures expose two tracks: s1_v (slides/screen capture, video-only)
# and s2_av (lecturer camera, video+audio). Download both as separate files.
STREAMS = [
    ('slides', 's1_v.m3u8'),
    ('camera', 's2_av.m3u8'),
]

def slug(s: str) -> str:
    s = re.sub(r'\s+', ' ', s or '').strip()
    s = re.sub(r'[^A-Za-z0-9._()\- ]+', '_', s)
    return s[:180].strip() or 'untitled'

def load_reg():
    if REG_PATH.exists():
        return json.loads(REG_PATH.read_text(encoding='utf-8'))
    return {'version': 1, 'courses': {}, 'items': []}

def save_reg(data):
    tmp = REG_PATH.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, REG_PATH)  # atomic — readers never see a half-written file

def upsert_item(item):
  with reg_lock():
    data = load_reg()
    items = data.setdefault('items', [])
    key = item['dedup_key']
    for i, old in enumerate(items):
        if old.get('dedup_key') == key:
            merged = dict(old)
            merged.update(item)
            merged['updated_at'] = int(time.time())
            items[i] = merged
            break
    else:
        item = dict(item)
        item.setdefault('created_at', int(time.time()))
        item['updated_at'] = int(time.time())
        items.append(item)
    courses = data.setdefault('courses', {})
    cname = item.get('course_name', 'UNKNOWN')
    courses.setdefault(cname, {'items': []})
    if key not in courses[cname]['items']:
        courses[cname]['items'].append(key)
    save_reg(data)

def is_done_or_pending(course_name, dedup_key):
    data = load_reg()
    for item in data.get('items', []):
        if item.get('dedup_key') == dedup_key and item.get('course_name') == course_name:
            if item.get('uploaded'):
                return True
            if item.get('downloaded') and item.get('upload_status') in {'pending', 'uploading'}:
                return True
            if item.get('downloaded') and os.path.exists(item.get('local_path', '')):
                return True
    return False

async def get_ua_and_cookies(ctx):
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    ua = await page.evaluate('navigator.userAgent')
    cookies = await ctx.cookies(['https://echo360.net.au', 'https://content.echo360.net.au'])
    cookie_header = '; '.join(f"{c['name']}={c['value']}" for c in cookies if c['name'] in COOKIE_NAMES)
    return ua, cookie_header

async def collect_rows(section_url):
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(section_url, wait_until='domcontentloaded', timeout=60000)
        await page.wait_for_timeout(3500)
        rows = page.locator('.class-row')
        count = await rows.count()
        out = []
        for i in range(count):
            row = rows.nth(i)
            text = re.sub(r'\s+', ' ', (await row.text_content() or '')).strip()
            aria = await row.get_attribute('aria-label') or ''
            out.append({'index': i, 'text': text, 'aria': aria})
        await browser.close()
        return out

async def capture_lesson(section_url, index):
    reqs = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        def on_req(req):
            u = req.url
            if '.m3u8' in u and 'content.echo360.net.au' in u:
                reqs.append(u)
        page.on('request', on_req)
        await page.goto(section_url, wait_until='domcontentloaded', timeout=60000)
        await page.wait_for_timeout(3500)
        row = page.locator('.class-row').nth(index)
        title = re.sub(r'\s+', ' ', (await row.text_content() or '')).strip()
        aria = await row.get_attribute('aria-label') or ''
        await row.click(timeout=15000)
        await page.wait_for_timeout(9000)
        lesson_url = page.url
        ua, cookie_header = await get_ua_and_cookies(ctx)
        await browser.close()
    uniq = []
    seen = set()
    for u in reqs:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    streams = {}
    for tag, suffix in STREAMS:
        streams[tag] = next((u for u in uniq if suffix in u), None)
    dedup_key = None
    m = re.search(r'/lesson/([^/]+)/classroom', lesson_url)
    if m:
        dedup_key = m.group(1)
    return {
        'title': title,
        'aria': aria,
        'lesson_url': lesson_url,
        'streams': streams,
        'ua': ua,
        'cookie_header': cookie_header,
        'dedup_key': dedup_key or lesson_url,
    }

MIN_FREE_GB = 8  # pause new downloads below this so the upload+cleanup pipeline can catch up

def free_space_gb(path='/home/colin'):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / 1e9

def wait_for_disk_space():
    waited = False
    while free_space_gb() < MIN_FREE_GB:
        if not waited:
            print(f'DISK_LOW: free={free_space_gb():.1f}GB < {MIN_FREE_GB}GB — pausing new downloads, waiting for upload+cleanup to free space')
            waited = True
        time.sleep(30)
    if waited:
        print(f'DISK_OK: free={free_space_gb():.1f}GB — resuming downloads')

def ffmpeg_download(m3u8, lesson_url, ua, cookie_header, out_path):
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning', '-stats',
        '-user_agent', ua,
        '-headers', f'Referer: {lesson_url}\r\nCookie: {cookie_header}\r\n',
        '-i', m3u8,
        '-c', 'copy', str(out_path)
    ]
    return subprocess.call(cmd)

def main():
    if len(sys.argv) < 4:
        print('usage: python3 echo360_batch_download.py <COURSE_NAME> <SECTION_URL> <OUT_DIR>')
        raise SystemExit(1)
    course_name, section_url, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = asyncio.run(collect_rows(section_url))
    print(f'FOUND_ROWS {len(rows)}')
    for row in rows:
        print('ROW', row['index'], row['text'])
    for row in rows:
        print(f'PROCESS_ROW {row["index"]}')
        try:
            meta = asyncio.run(capture_lesson(section_url, row['index']))
        except Exception as e:
            print('CAPTURE_FAIL', row['index'], repr(e))
            continue

        base_dedup_key = f'{course_name}::{meta["dedup_key"]}'
        streams = meta.get('streams') or {}

        if not any(streams.values()):
            print('NO_M3U8', row['index'], meta['lesson_url'])
            upsert_item({
                'dedup_key': base_dedup_key,
                'course_name': course_name,
                'title': meta['title'],
                'platform': 'echo360',
                'lesson_url': meta['lesson_url'],
                'downloaded': False,
                'uploaded': False,
                'upload_status': 'not_ready',
                'note': 'no_m3u8',
            })
            continue

        for tag, _suffix in STREAMS:
            m3u8 = streams.get(tag)
            if not m3u8:
                print(f'NO_STREAM[{tag}]', row['index'])
                continue

            stream_key = f'{base_dedup_key}::{tag}'
            # Camera stream may already exist under the legacy (pre-dual-stream) dedup_key
            # which has no ::tag suffix — treat that as satisfied too, don't re-download.
            legacy_satisfied = (tag == 'camera') and is_done_or_pending(course_name, base_dedup_key)
            if legacy_satisfied or is_done_or_pending(course_name, stream_key):
                print('SKIP_EXISTING', stream_key)
                continue

            label = 'PPT' if tag == 'slides' else 'Camera'
            filename = slug(meta['title']) + f' ({label}).mp4'
            out_path = out_dir / filename
            upsert_item({
                'dedup_key': stream_key,
                'course_name': course_name,
                'title': meta['title'],
                'stream_tag': tag,
                'platform': 'echo360',
                'lesson_url': meta['lesson_url'],
                'm3u8': m3u8,
                'local_path': str(out_path),
                'downloaded': False,
                'uploaded': False,
                'upload_status': 'pending',
                'note': 'queued',
            })
            wait_for_disk_space()
            rc = ffmpeg_download(m3u8, meta['lesson_url'], meta['ua'], meta['cookie_header'], out_path)
            if rc == 0 and out_path.exists():
                upsert_item({
                    'dedup_key': stream_key,
                    'course_name': course_name,
                    'title': meta['title'],
                    'stream_tag': tag,
                    'platform': 'echo360',
                    'lesson_url': meta['lesson_url'],
                    'm3u8': m3u8,
                    'local_path': str(out_path),
                    'size_bytes': out_path.stat().st_size,
                    'downloaded': True,
                    'uploaded': False,
                    'upload_status': 'pending',
                    'note': 'downloaded',
                })
                print('DOWNLOADED', out_path)
            else:
                upsert_item({
                    'dedup_key': stream_key,
                    'course_name': course_name,
                    'title': meta['title'],
                    'stream_tag': tag,
                    'platform': 'echo360',
                    'lesson_url': meta['lesson_url'],
                    'm3u8': m3u8,
                    'local_path': str(out_path),
                    'downloaded': False,
                    'uploaded': False,
                    'upload_status': 'failed',
                    'note': f'ffmpeg_rc_{rc}',
                })
                print('DOWNLOAD_FAILED', out_path, rc)

if __name__ == '__main__':
    main()
