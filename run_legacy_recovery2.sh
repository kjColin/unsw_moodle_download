#!/bin/bash
# 第二批复查：剩余仍有 no_m3u8 缺口的 section。
# 多数条目只记到 section 首页，无法单独探测，只能整门课重扫；下载器幂等，
# 已完成的会 SKIP_EXISTING，所以代价只是一次列举。
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

# COMP9414 排最前：7 条都只记到 section 首页，疑似与 COMP9020 同为分组布局
run COMP9414 9d19c169-0d23-432b-bbcf-0e7eb50323a5 ""
run COMP9024 3c9b1e80-3181-46f4-82c2-22929ae636e6 ""
run COMP9511 d614c1c2-b29d-454d-b0c8-51858f2b59ce 1PGA
# 这个 section 不在原 README 里，2026-11-21 从 echo360.net.au/courses 发现
run COMP9511 cc1cb01e-d2e7-448e-b9b7-ed07be727f2a 1PGB
run COMP9021 662dd9c9-015f-4180-a3ce-97befd152f2a Tuesday
run COMP9021 43b5321d-05d4-4472-ba3a-580f8fe83992 Thursday
run COMP9311 905cfe64-79a9-4206-b24f-999b975c20fc Tuesday
run COMP9311 aa3951d6-347e-47a7-a956-6d086d1c5ecf Thursday
run COMP9417 4e8ce04c-07d9-4291-9800-d296cb842f11 ""
run COMP9517 696b1e73-0510-4f96-bb89-af4c6314face ""
run COMP3331 9026bba1-589a-435a-9b9e-172cb60c2be6 ""
run COMP2041 4eea7213-f208-4d40-8a1c-5b4218805186 ""

echo "=== LEGACY_RECOVERY2_DONE $(date '+%F %T') ==="
