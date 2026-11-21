#!/bin/bash
# 复查 T1/T2 当初被记为 no_m3u8 的录播：其中多数其实是单流(s1_av)内容，
# 在加入单流回退与分组展开之前会被误判为"录播未生成"。
# 下载器幂等，已完成的条目会跳过，只抓当初漏掉的。
cd /home/colin/video_pipeline
BASE=/home/colin/Downloads/moodle_videos

run() {
  local course="$1" section_id="$2" subdir="$3"
  local out="$BASE/$course"; [ -n "$subdir" ] && out="$out/$subdir"
  echo "=== START $course ${subdir:+($subdir)} $(date '+%F %T') ==="
  if python3 echo360_batch_download.py "$course" \
      "https://echo360.net.au/section/$section_id/home" "$out" \
      > "/tmp/echo_${course}_${subdir:-main}_recover.log" 2>&1; then
    echo "=== DONE $course ${subdir:+($subdir)} $(date '+%F %T') ==="
  else
    echo "=== FAILED $course ${subdir:+($subdir)} rc=$? $(date '+%F %T') ==="
  fi
}

# 先跑可恢复量最大的两门（8 + 7 = 15 条，占七成）
run COMP9020 3e3079ad-1e24-440b-ba6c-3bb372021509 SectionA
run COMP9020 3e49b136-2536-4356-bf11-b6d82329e582 SectionB
run COMP9517 696b1e73-0510-4f96-bb89-af4c6314face ""

echo "=== LEGACY_RECOVERY_DONE $(date '+%F %T') ==="
