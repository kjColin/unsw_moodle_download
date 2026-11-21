# UNSW Moodle → 百度网盘 + Google Drive 视频迁移流水线

Echo360 课程录播（双流：PPT + 摄像头）批量下载 → **同时上传百度网盘和 Google Drive** →
两边各自校验 → 只有两边都通过才删除本地，
下载与上传可并发运行（registry 用 flock 互斥 + 原子写保证一致性）。

## 双传规则（2026-11-19 起）

- 任一边上传或校验失败 → **保留本地文件**，下一轮重试。绝不在只成功一边时删本地。
- Drive remote 未配置时上传器直接退出（rc=2），`run_upload_loop.sh` 随之中止，
  避免只传百度、攒下一堆永远清不掉的本地文件。
- registry 新增字段：`gdrive_uploaded`、`gdrive_status`、`gdrive_dir`。
  旧条目没有 `gdrive_uploaded`，按规则不可删——本地还在的会被补传 Drive。
- Drive 路径：`UNSW-Backup/{课程代码}/Lectures/`（remote 名 `gdrive`），百度路径不变。
- 校验：百度查远端 ls 列表命中文件名；Drive 用 `rclone lsjson` 比对字节数，必须完全相等。
- `test_upload_gates.py` 锁住上述删除/待办规则：`python3 -m unittest test_upload_gates`

## 状态

- 2026-07-07：T1/T2 全部 10 门课完成：332 个视频（166 节课 × 双流）已传百度并清理本地。
  百度路径 `/Unsw/{课程代码}/Lectures/`。**这批本地副本已删，没有 Drive 备份**；
  要补传 Drive 只能从百度下回来再传（88 GB，单文件逐个周转），尚未做。
- 2026-11-19：加入 Drive 双传。待办范围 = 2026 T3 的 COMP9900 / COMP4418 / COMP6714，
  这三门课的 Echo360 section UUID 尚未录入（需登录 Moodle 后抓取）。
- registry 中另有 36 条 `no_m3u8 / not_ready`：Echo360 未生成录播流，重跑也拿不到。

## 脚本

| 脚本 | 作用 |
|---|---|
| `echo360_batch_download.py` | 核心下载器。用法：`python3 echo360_batch_download.py <课程> <SECTION_URL> <输出目录>`。通过 CDP (127.0.0.1:9222) 连已登录浏览器，抓取每节课的 s1_v(PPT)/s2_av(摄像头) m3u8，ffmpeg 下载为独立 mp4。磁盘剩余 <8GB 自动暂停。已下载/已上传的自动跳过（幂等，可随时重跑补漏） |
| `upload_and_clean_videos.py` | 上传器。扫 registry 中 downloaded 且未 uploaded 的文件，BaiduPCS-Go 上传 → 远端校验 → 删本地 → 记录日志。单批处理后退出 |
| `run_upload_loop.sh` | 循环跑上传器，直到无下载进程且无待上传文件时自动退出 |
| `run_new_courses_rescan.sh` | 批量重扫示例：按课程/section 顺序串行调下载器（共享一个浏览器标签页，不能并行）。上传循环可同时运行 |
| `moodle_resource_download.py` | 配套：下载 Moodle 课程资料（PDF 等）到 /home/colin/Unsw/ |
| `upload_moodle_resources.py` | 配套：课程资料上传网盘并清理本地（独立 registry：moodle_resource_registry.json） |

## 网盘目录结构

- **Google Drive**：`UNSW-Backup/<学期>/<课程>/Lectures/`，学期映射见 `course_terms.json`
  （新学期加课补一行；未映射的课落到 `Unsorted`，不会导致上传失败）。
- **百度网盘**：`/Unsw/<课程>/Lectures/`，不分学期。两边结构不同是有意的——
  百度上已有 400+ 个历史文件，重组收益不大。

## 课件与总结

`upload_moodle_resources.py` 把 `/home/colin/Unsw` 下所有课程的课件和双语总结双传到
百度（`/Unsw/<相对路径>`，布局不变）和 Drive（`UNSW-Backup/<学期>/<课程>/...`，总结放在
`<课程>/Summaries/` 下，跟着它总结的课件走）。每日流水线 Step3b 会自动调用它。

- **课程从目录自动发现**，不写死列表——写死的列表正是 T3 课件从没上传过的原因。
- **不删本地副本**。课件下载器按"本地文件是否存在"决定要不要下载，旧版传完百度就删本地，
  结果每天都把同一批课件重新下载一遍。课件一学期才几十 MB，留着没成本；该删的是视频。
- `restore_resources_from_baidu.py`：把只在百度上、本地已删的课件按原路径取回，之后上传器
  会只补 Drive。百度对这个账号限速约 0.2 MB/s，课件量小无所谓。
- 账本：`/home/colin/moodle_resource_registry.json`（按本地路径为键，字段 `uploaded`/`gdrive_uploaded`）。

## 只在百度的视频补到 Drive

`run_gdrive_mirror.sh`：**从 Echo360 重抓而不是从百度下载**——百度非会员实测 0.23 MB/s
（88 GB 约 4 天半），Echo360 约 13 MB/s（约 2 小时）。下载器的 `baidu_state_for()` 把旧行的
"已在百度"状态继承给新下载的行，上传器据此跳过百度、只传 Drive；2026-11-21 补齐 332 个，
百度上的文件修改时间未变，证明没有重传。双流改造前的老条目把摄像头流存在不带 `::camera`
的键下，重抓时也继承其百度状态，老条目标记 `superseded_by`。

"完成"的定义是**两端都有**（`uploaded and gdrive_uploaded`），所以以后任何一边缺了，重扫都会补上。
`test_mirror_rules.py` 锁住这些规则。

## 账本里"未下载"条目的含义

- `no_media_confirmed`：确实没有录播（如 Flexibility Week、无流的占位视频），无需再试
- `superseded_single_stream_fix`：早期失败的尝试，同一节课已在 `::single` 键下抓到
- `stale_section_home_artifact`：失败运行把 section 首页当成课程记下的残留，不代表缺口

查缺口不要直接数"未下载"条数——按 lesson UUID 聚合，看该节课是否至少有一路流已下载。

## 数据文件（不在本目录，勿删）

- `/home/colin/video_sync_registry.json` — 视频总账（每个视频的下载/上传/清理状态）
- `/home/colin/video_sync_registry.lock` — flock 锁文件（下载器与上传器共用）
- `/home/colin/moodle_resource_registry.json` / `.lock` — 课程资料账本

## 依赖

- 已登录 Moodle/Echo360 的 Chromium，开着 CDP 端口 9222（`launch_browser_detached.py`，见下文"浏览器"一节）
- `ffmpeg`、`playwright`（Python）、`/home/colin/.local/bin/BaiduPCS-Go`（已登录）

## 已知 Echo360 Section UUID

2026 T3 已完成（2026-11-21）：COMP4418 36 个文件、COMP9900 18 个、COMP6714 31 个
（9 节现场录播双流 + 13 条预录单流），百度与 Drive 两端均校验通过、本地已清理。

### Section UUID

2026 T3（2026-11-21 抓取，录播条数为当时 Echo360 显示值）：
```
COMP6714  8602d36d-5b27-4e87-8d5a-2a5803ee7456   (22 条)
COMP4418  fa63bd95-15ff-4ebd-9460-73f433a3aaff   (18 条)
COMP9900  bd200f55-0ffe-44f6-9301-1cd7ebd96b2f   (9 条, Moodle 上课名为 COMP3900/COMP9900)
```
注：`cc1cb01e-d2e7-448e-b9b7-ed07be727f2a` 是 COMP9511 的 2026T1 另一 section(1PGB)，非 T3。

T1/T2：
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

## 两种 section 布局 / 两种流

- **平铺**：课程行直接是 `.class-row`，一节课两路流 `s1_v`(PPT) + `s2_av`(摄像头)。
- **分组**：录播装在可折叠分组里（COMP6714 的 Live / Pre-recorded 两组）。折叠时
  页面上只有分组标题，点它抓不到流，整门课会被误判为空。`expand_groups()` 每次
  加载页面后点开所有 `button.opener`，`lesson_rows()` 用 `.class-row:not(.group)`
  排除标题本身。分组在每次导航后都会折叠回去，所以列举和点击两处都要展开。
- **单流**：预录内容只有一路画面，发布为 `s1_av`（音视频合一），不是上面那对双流。
  匹配不到双流时回退到单流，文件名标签为 `(AV)`。
- 点开课程后用轮询等流（最多 24s，一有请求就继续），预录内容出流比双流慢。

## 怎么找新学期的 Section UUID

**别走 Moodle 的 LTI 链接**：`mod/lti/view.php` 页面不含 Echo360 地址，加 `forceview=1`
也不会在页面或 iframe 里暴露 section UUID，也不开新标签页，这条路试过，走不通。

直接用已登录的 CDP 浏览器打开 `https://echo360.net.au/courses`，页面会列出全部
`https://echo360.net.au/section/<UUID>/home` 链接。课程名不要从课程列表页的 DOM 上溯去取
（父元素会抓到整个网格的文本，导致每一行都误判成同一门课），而是逐个打开
`/section/<UUID>/home`，读页面里的 `h1`/courseName，那里有准确的课程代码和学期。

## 补新课/新周录播的用法

学期中每周出新录播后，重跑对应 section 即可（幂等跳过已完成项）：

```bash
cd /home/colin/video_pipeline
# 终端1：下载（可多个 section 串行）
python3 echo360_batch_download.py COMP9024 "https://echo360.net.au/section/3c9b1e80-3181-46f4-82c2-22929ae636e6/home" /home/colin/Downloads/moodle_videos/COMP9024
# 终端2：上传循环（并发安全）
./run_upload_loop.sh
```
