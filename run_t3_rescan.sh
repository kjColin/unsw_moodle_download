#!/bin/bash
# 串行下载 2026 T3 三门课的 Echo360 录播（共享同一个 CDP 标签页，不能并行）。
# 上传循环 run_upload_loop.sh 可同时运行（registry 有 flock 互斥）。
set -e
cd /home/colin/video_pipeline
BASE=/home/colin/Downloads/moodle_videos

run() {
  local course="$1" section_id="$2"
  echo "=== START $course [$section_id] $(date '+%F %T') ==="
  python3 echo360_batch_download.py "$course" \
    "https://echo360.net.au/section/$section_id/home" "$BASE/$course" \
    > "/tmp/echo_${course}_t3.log" 2>&1
  echo "=== DONE $course $(date '+%F %T') ==="
}

run COMP6714 8602d36d-5b27-4e87-8d5a-2a5803ee7456
run COMP4418 fa63bd95-15ff-4ebd-9460-73f433a3aaff
run COMP9900 bd200f55-0ffe-44f6-9301-1cd7ebd96b2f

echo "=== ALL_T3_RESCAN_DONE $(date '+%F %T') ==="
