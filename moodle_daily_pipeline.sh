#!/bin/bash
set -euo pipefail

# 全部脚本集中在本仓库；敏感值放 config.sh（不进版本库）。
REPO="/home/colin/video_pipeline"
# shellcheck source=/dev/null
. "$REPO/config.sh"

LOG=/tmp/moodle_cron.log
TS=$(date '+%F %T %Z')
REPORT=/tmp/moodle_report.json
NOTIFY_SENT=/tmp/moodle_last_notify_hash.txt

send_notify() {
  local msg="$1"
  # best-effort notification via openclaw message CLI
  if command -v openclaw >/dev/null 2>&1; then
    openclaw message send \
      --channel telegram \
      --target "${TELEGRAM_TARGET:?config.sh 未设置 TELEGRAM_TARGET}" \
      --message "$msg" >/dev/null 2>&1 || true
  fi
}

emit_alerts_from_report() {
  [ -f "$REPORT" ] || return 0

  local payload hash
  payload=$(python3 - <<'PY'
import json
p='/tmp/moodle_report.json'
try:
    j=json.load(open(p,encoding='utf-8'))
except Exception:
    print('')
    raise SystemExit(0)
alerts=j.get('alerts') or []
if not alerts:
    print('')
    raise SystemExit(0)
lines=[]
for a in alerts[:20]:
    t=a.get('type')
    if t=='new_event':
        e=a.get('event',{})
        lines.append(f"🆕 新作业/任务: {e.get('name','')} | due={e.get('due_iso') or 'N/A'}")
    elif t=='due_changed':
        b=a.get('before',{}); c=a.get('after',{})
        lines.append(f"🔁 截止变化: {c.get('name','')} | {b.get('due_iso') or 'N/A'} -> {c.get('due_iso') or 'N/A'}")
    elif t=='due_48h':
        e=a.get('event',{})
        lines.append(f"⏰ 48h内截止: {e.get('name','')} | in {e.get('hours_left')}h")
msg='📚 Moodle提醒\n' + '\n'.join(lines)
print(msg)
PY
)

  [ -n "$payload" ] || return 0
  hash=$(printf "%s" "$payload" | sha256sum | awk '{print $1}')

  if [ -f "$NOTIFY_SENT" ] && [ "$(cat $NOTIFY_SENT 2>/dev/null || true)" = "$hash" ]; then
    echo "[$TS] alert unchanged, skip duplicate notify"
    return 0
  fi

  send_notify "$payload"
  echo "$hash" > "$NOTIFY_SENT"
  echo "[$TS] alert notified"
}

{
  echo "[$TS] ===== Moodle Daily Pipeline START ====="

  echo "[$TS] Step1: Check upcoming events via CDP"
  if su - colin -c "python3 $REPO/moodle_check_cdp.py"; then
    echo "[$TS] moodle_check_cdp done"
  else
    echo "[$TS] WARN: moodle_check_cdp failed (login/tab issue); keep last valid report"
  fi

  echo "[$TS] Step2: Extract NEW files via CDP"
  if su - colin -c "python3 $REPO/moodle_extract_pdfs_cdp.py"; then
    echo "[$TS] file extraction done"
  else
    echo "[$TS] WARN: file extraction failed"
  fi

  echo "[$TS] Step3: Summarize only NEW Lectures/Tutorials (bilingual)"
  if python3 "$REPO/summarize_new_pdfs_bilingual.py"; then
    echo "[$TS] Incremental bilingual summary done"
  else
    echo "[$TS] WARN: incremental bilingual summary failed"
  fi

  echo "[$TS] Step4: Notify assignment updates / due-date changes / 48h reminders"
  emit_alerts_from_report

  echo "[$TS] ===== Moodle Daily Pipeline END ====="
  echo
} >> "$LOG" 2>&1
