#!/bin/bash
# 把只在百度上的 T1/T2 录播补到 Google Drive。
# 源头用 Echo360 而不是百度：百度非会员实测 0.23 MB/s（88 GB 约 4 天半），
# Echo360 约 13 MB/s。下载器把"已在百度"的状态继承到新行（baidu_state_for），
# 上传器据此跳过百度、只传 Drive。下载器幂等，可随时重跑补漏。
cd /home/colin/video_pipeline
BASE=/home/colin/Downloads/moodle_videos

run() {
  local course="$1" section_id="$2" subdir="$3"
  local out="$BASE/$course"; [ -n "$subdir" ] && out="$out/$subdir"
  echo "=== START $course ${subdir:+($subdir)} $(date '+%F %T') ==="
  if python3 -u echo360_batch_download.py "$course" \
      "https://echo360.net.au/section/$section_id/home" "$out" \
      > "/tmp/echo_${course}_${subdir:-main}_mirror.log" 2>&1; then
    echo "=== DONE $course ${subdir:+($subdir)} $(date '+%F %T') ==="
  else
    echo "=== FAILED $course ${subdir:+($subdir)} rc=$? $(date '+%F %T') ==="
  fi
}

run COMP3331 9026bba1-589a-435a-9b9e-172cb60c2be6 ""
run COMP9020 3e3079ad-1e24-440b-ba6c-3bb372021509 SectionA
run COMP9020 3e49b136-2536-4356-bf11-b6d82329e582 SectionB
run COMP9021 662dd9c9-015f-4180-a3ce-97befd152f2a Tuesday
run COMP9021 43b5321d-05d4-4472-ba3a-580f8fe83992 Thursday
run COMP9024 3c9b1e80-3181-46f4-82c2-22929ae636e6 ""
run COMP9311 905cfe64-79a9-4206-b24f-999b975c20fc Tuesday
run COMP9311 aa3951d6-347e-47a7-a956-6d086d1c5ecf Thursday
run COMP9414 9d19c169-0d23-432b-bbcf-0e7eb50323a5 ""
run COMP9417 4e8ce04c-07d9-4291-9800-d296cb842f11 ""
run COMP9511 d614c1c2-b29d-454d-b0c8-51858f2b59ce 1PGA
run COMP9517 696b1e73-0510-4f96-bb89-af4c6314face ""

echo "=== GDRIVE_MIRROR_DONE $(date '+%F %T') ==="
