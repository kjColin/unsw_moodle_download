#!/bin/bash
# Loop upload_and_clean_videos.py (it processes one snapshot batch then exits)
# so newly-downloaded files keep getting picked up while any rescan is running.
# Exits when no echo360 download is running AND nothing is left to upload.
cd /home/colin/video_pipeline

# 单实例保护。两个循环同时跑会抢同一批文件：一个传完双端并删掉本地，另一个
# 随后在已删除的文件上跑 rclone，报 "Source doesn't exist" 并把 registry 的
# 状态字段覆写成 failed。数据不会丢（删除仍需两端校验通过），但白费带宽、
# 状态也会乱。-n 表示拿不到锁就立刻退出，而不是排队。
exec 9>/home/colin/video_sync_upload_loop.lock
if ! flock -n 9; then
  echo "=== 已有上传循环在运行，本次退出 ==="
  exit 0
fi

while true; do
  # -u：stdout 重定向到文件时 python 默认按块缓冲，进度要攒满几 KB 才落盘，
  # 看起来像卡住了。关掉缓冲，日志才是实时的。
  python3 -u upload_and_clean_videos.py >> /tmp/upload_pipeline.log 2>&1
  rc=$?
  echo "--- upload batch pass complete (rc=$rc), checking for more work ---" >> /tmp/upload_pipeline.log

  # rc=2 means a remote isn't configured; retrying can only reprint the refusal.
  if [ "$rc" -eq 2 ]; then
    echo "=== UPLOAD_LOOP_ABORT: uploader refused to run, see refusal above ===" >> /tmp/upload_pipeline.log
    exit 2
  fi

  rescan_alive=0
  # 只匹配脚本名：下载器常以 `python3 -u ...` 启动，带上解释器参数的模式会漏掉它，
  # 循环就会在文件还没下完时以为"没有下载器、队列为空"而提前退出。
  # [d] 让 pgrep 不匹配到自己这条命令行。
  pgrep -f 'echo360_batch_[d]ownload\.py' > /dev/null && rescan_alive=1

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
