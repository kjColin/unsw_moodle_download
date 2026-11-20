#!/bin/bash
# 重跑 COMP9900 和 COMP6714（串行，共享同一个 CDP 标签页）。
# COMP9900 首次失败于文件权限（源码被 root 改成 colin 不可读），COMP6714 首次
# 失败于录播分组未展开；两者都已修好。下载器幂等，已完成的会自动跳过。
# 注意不要用 set -e：一门课失败不该让后面的课也不跑。
cd /home/colin/video_pipeline
BASE=/home/colin/Downloads/moodle_videos

run() {
  local course="$1" section_id="$2"
  echo "=== START $course [$section_id] $(date '+%F %T') ==="
  if python3 echo360_batch_download.py "$course" \
      "https://echo360.net.au/section/$section_id/home" "$BASE/$course" \
      > "/tmp/echo_${course}_t3.log" 2>&1; then
    echo "=== DONE $course $(date '+%F %T') ==="
  else
    echo "=== FAILED $course rc=$? $(date '+%F %T') — 见 /tmp/echo_${course}_t3.log ==="
  fi
}

run COMP9900 bd200f55-0ffe-44f6-9301-1cd7ebd96b2f
run COMP6714 8602d36d-5b27-4e87-8d5a-2a5803ee7456

echo "=== ALL_T3_RESCAN_DONE $(date '+%F %T') ==="
