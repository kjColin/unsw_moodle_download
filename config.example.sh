#!/bin/bash
# 复制为 config.sh 并填入真实值。config.sh 不进版本库（见 .gitignore）。
# moodle_daily_pipeline.sh 会 source 它。

# 提醒推送目标，openclaw message send --target 的参数。
# 形如 telegram:<chat id>
TELEGRAM_TARGET="telegram:000000000"
