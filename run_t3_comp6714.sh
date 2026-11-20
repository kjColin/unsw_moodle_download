#!/bin/bash
# 单独重跑 COMP6714：它的录播放在折叠分组里，在 echo360_batch_download.py
# 加上 expand_groups() 之前这门课会被误判为空（NO_M3U8）。
set -e
cd /home/colin/video_pipeline
python3 echo360_batch_download.py COMP6714 \
  "https://echo360.net.au/section/8602d36d-5b27-4e87-8d5a-2a5803ee7456/home" \
  /home/colin/Downloads/moodle_videos/COMP6714
