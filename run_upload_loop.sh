#!/bin/bash
# Loop upload_and_clean_videos.py (it processes one snapshot batch then exits)
# so newly-downloaded files keep getting picked up while any rescan is running.
# Exits when no echo360 download is running AND nothing is left to upload.
cd /home/colin/video_pipeline

while true; do
  python3 upload_and_clean_videos.py >> /tmp/upload_pipeline.log 2>&1
  rc=$?
  echo "--- upload batch pass complete (rc=$rc), checking for more work ---" >> /tmp/upload_pipeline.log

  # rc=2 means a remote isn't configured; retrying can only reprint the refusal.
  if [ "$rc" -eq 2 ]; then
    echo "=== UPLOAD_LOOP_ABORT: uploader refused to run, see refusal above ===" >> /tmp/upload_pipeline.log
    exit 2
  fi

  rescan_alive=0
  pgrep -f 'python3 echo360_batch_download.py' > /dev/null && rescan_alive=1

  # Pending means "owes either remote" — same rule the uploader uses.
  pending=$(python3 - <<'EOF'
import json, os, sys
from pathlib import Path
sys.path.insert(0, '/home/colin/video_pipeline')
from upload_and_clean_videos import needs_work
data = json.loads(Path('/home/colin/video_sync_registry.json').read_text())
print(sum(1 for it in data['items']
          if needs_work(it) and os.path.exists(it.get('local_path', ''))))
EOF
)

  if [ "$rescan_alive" -eq 0 ] && [ "$pending" -eq 0 ]; then
    echo "=== UPLOAD_LOOP_DONE: no rescan running and no pending uploads remain ===" >> /tmp/upload_pipeline.log
    break
  fi
  sleep 45
done
