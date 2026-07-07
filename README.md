# UNSW Moodle → 百度网盘 视频迁移流水线

Echo360 课程录播（双流：PPT + 摄像头）批量下载 → 上传百度网盘 → 校验 → 删除本地，
下载与上传可并发运行（registry 用 flock 互斥 + 原子写保证一致性）。

## 状态（2026-07-07）

全部 10 门课已完成：332 个视频（166 节课 × 双流）全部下载、上传、本地清理完毕。
网盘路径：`/Unsw/{课程代码}/Lectures/`。

## 脚本

| 脚本 | 作用 |
|---|---|
| `echo360_batch_download.py` | 核心下载器。用法：`python3 echo360_batch_download.py <课程> <SECTION_URL> <输出目录>`。通过 CDP (127.0.0.1:9222) 连已登录浏览器，抓取每节课的 s1_v(PPT)/s2_av(摄像头) m3u8，ffmpeg 下载为独立 mp4。磁盘剩余 <8GB 自动暂停。已下载/已上传的自动跳过（幂等，可随时重跑补漏） |
| `upload_and_clean_videos.py` | 上传器。扫 registry 中 downloaded 且未 uploaded 的文件，BaiduPCS-Go 上传 → 远端校验 → 删本地 → 记录日志。单批处理后退出 |
| `run_upload_loop.sh` | 循环跑上传器，直到无下载进程且无待上传文件时自动退出 |
| `run_new_courses_rescan.sh` | 批量重扫示例：按课程/section 顺序串行调下载器（共享一个浏览器标签页，不能并行）。上传循环可同时运行 |
| `moodle_resource_download.py` | 配套：下载 Moodle 课程资料（PDF 等）到 /home/colin/Unsw/ |
| `upload_moodle_resources.py` | 配套：课程资料上传网盘并清理本地（独立 registry：moodle_resource_registry.json） |

## 数据文件（不在本目录，勿删）

- `/home/colin/video_sync_registry.json` — 视频总账（每个视频的下载/上传/清理状态）
- `/home/colin/video_sync_registry.lock` — flock 锁文件（下载器与上传器共用）
- `/home/colin/moodle_resource_registry.json` / `.lock` — 课程资料账本

## 依赖

- 已登录 Moodle/Echo360 的 Chromium，开着 CDP 端口 9222（`/home/colin/start_openclaw_browser.sh`）
- `ffmpeg`、`playwright`（Python）、`/home/colin/.local/bin/BaiduPCS-Go`（已登录）

## 已知 Echo360 Section UUID

```
COMP9511  d614c1c2-b29d-454d-b0c8-51858f2b59ce
COMP9417  4e8ce04c-07d9-4291-9800-d296cb842f11
COMP9414  9d19c169-0d23-432b-bbcf-0e7eb50323a5
COMP2041  4eea7213-f208-4d40-8a1c-5b4218805186
COMP9311  905cfe64-79a9-4206-b24f-999b975c20fc (Tue) / aa3951d6-347e-47a7-a956-6d086d1c5ecf (Thu)
COMP9024  3c9b1e80-3181-46f4-82c2-22929ae636e6
COMP9517  696b1e73-0510-4f96-bb89-af4c6314face
COMP3331  9026bba1-589a-435a-9b9e-172cb60c2be6
COMP9020  3e3079ad-1e24-440b-ba6c-3bb372021509 (A) / 3e49b136-2536-4356-bf11-b6d82329e582 (B)
COMP9021  662dd9c9-015f-4180-a3ce-97befd152f2a (Tue) / 43b5321d-05d4-4472-ba3a-580f8fe83992 (Thu)
```
Section 主页 URL 格式：`https://echo360.net.au/section/<UUID>/home`

## 补新课/新周录播的用法

学期中每周出新录播后，重跑对应 section 即可（幂等跳过已完成项）：

```bash
cd /home/colin/video_pipeline
# 终端1：下载（可多个 section 串行）
python3 echo360_batch_download.py COMP9024 "https://echo360.net.au/section/3c9b1e80-3181-46f4-82c2-22929ae636e6/home" /home/colin/Downloads/moodle_videos/COMP9024
# 终端2：上传循环（并发安全）
./run_upload_loop.sh
```
