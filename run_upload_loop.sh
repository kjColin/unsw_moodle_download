#!/bin/bash
# Loop upload_and_clean_videos.py (it processes one snapshot batch then exits)
# so newly-downloaded files keep getting picked up while any rescan is running.
# Exits when no echo360 download is running AND nothing is left to upload.
cd /home/colin/video_pipeline

while true; do
  python3 upload_and_clean_videos.py >> /tmp/upload_pipeline.log 2>&1
  echo "--- upload batch pass complete, checking for more work ---" >> /tmp/upload_pipeline.log

  rescan_alive=0
  pgrep -f 'python3 echo360_batch_download.py' > /dev/null && rescan_alive=1

  pending=$(python3 - <<'EOF'
import json, os
from pathlib import Path
data = json.loads(Path('/home/colin/video_sync_registry.json').read_text())
items = data['items']
print(sum(1 for it in items if it.get('downloaded') and not it.get('uploaded') and os.path.exists(it.get('local_path',''))))
EOF
)

  if [ "$rescan_alive" -eq 0 ] && [ "$pending" -eq 0 ]; then
    echo "=== UPLOAD_LOOP_DONE: no rescan running and no pending uploads remain ===" >> /tmp/upload_pipeline.log
    break
  fi
  sleep 45
done
