#!/bin/bash
# Sequentially rescan Echo360 sections for the 7 newly-discovered courses.
# Runs one at a time (shares the CDP browser tab with no other rescans),
# while upload_and_clean_videos.py keeps running concurrently (safe now via flock).
set -e
cd /home/colin/video_pipeline
BASE=/home/colin/Downloads/moodle_videos

run() {
  local course="$1" section_id="$2" subdir="$3"
  local out="$BASE/$course"
  [ -n "$subdir" ] && out="$out/$subdir"
  echo "=== START $course ${subdir:+($subdir)} [$section_id] ==="
  python3 echo360_batch_download.py "$course" "https://echo360.net.au/section/$section_id/home" "$out" \
    > "/tmp/echo_${course}_${subdir:-main}_dual.log" 2>&1
  echo "=== DONE $course ${subdir:+($subdir)} ==="
}

run COMP2041  4eea7213-f208-4d40-8a1c-5b4218805186 ""
run COMP9311  905cfe64-79a9-4206-b24f-999b975c20fc Tuesday
run COMP9311  aa3951d6-347e-47a7-a956-6d086d1c5ecf Thursday
run COMP9024  3c9b1e80-3181-46f4-82c2-22929ae636e6 ""
run COMP9517  696b1e73-0510-4f96-bb89-af4c6314face ""
run COMP3331  9026bba1-589a-435a-9b9e-172cb60c2be6 ""
run COMP9020  3e3079ad-1e24-440b-ba6c-3bb372021509 SectionA
run COMP9020  3e49b136-2536-4356-bf11-b6d82329e582 SectionB
run COMP9021  662dd9c9-015f-4180-a3ce-97befd152f2a Tuesday
run COMP9021  43b5321d-05d4-4472-ba3a-580f8fe83992 Thursday

echo "=== ALL_NEW_COURSES_RESCAN_DONE ==="
