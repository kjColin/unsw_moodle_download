#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check Moodle upcoming events via existing logged-in CDP browser.

Features added:
- change detection (added / due-date changed) against previous report
- 48h reminder tagging
- preserve last good report by only overwriting report on successful run
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from playwright.async_api import async_playwright

CDP_URL = "http://127.0.0.1:9222"
OUT = "/tmp/moodle_report.json"
PREV = "/tmp/moodle_report_prev.json"
URL = "https://moodle.telt.unsw.edu.au/calendar/view.php?view=upcoming"
TZ = "Australia/Sydney"  # Moodle profile uses server timezone (Australia/Sydney)

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def parse_due_from_text(text: str):
    if not text:
        return None, None

    # Example: Friday, 13 March, 11:55 PM
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{1,2}):(\d{2})\s*([AP]M)", text, re.I)
    if not m:
        return None, None

    day = int(m.group(1))
    mon_name = m.group(2).lower()
    hour = int(m.group(3))
    minute = int(m.group(4))
    ampm = m.group(5).upper()
    month = MONTHS.get(mon_name)
    if not month:
        return None, None

    # Assume current year (Moodle upcoming window is near-term)
    year = datetime.now().year
    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0

    # Moodle renders times in Australia/Sydney; ZoneInfo handles AEST/AEDT
    try:
        dt = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(TZ))
    except Exception:
        return None, None
    return dt.isoformat(), dt


def event_key(e):
    return f"{e.get('name','')}|{e.get('link','')}"


def diff_events(prev_events, cur_events):
    pmap = {event_key(x): x for x in (prev_events or [])}
    cmap = {event_key(x): x for x in (cur_events or [])}

    added = []
    changed = []

    for k, cur in cmap.items():
        if k not in pmap:
            added.append(cur)
            continue
        prev = pmap[k]
        if (prev.get("due_iso") or "") != (cur.get("due_iso") or ""):
            changed.append({"before": prev, "after": cur})

    return added, changed


async def main():
    report = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": TZ,
        "profile_used": "cdp:9222",
        "total": 0,
        "soon_48h": 0,
        "overdue": 0,
        "changes": {"added_count": 0, "changed_count": 0, "added": [], "changed": []},
        "alerts": [],
        "events": [],
    }

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        if not browser.contexts:
            raise RuntimeError("No browser context on CDP")
        ctx = browser.contexts[0]

        page = None
        for pg in ctx.pages:
            if "moodle.telt.unsw.edu.au" in (pg.url or ""):
                page = pg
                break
        if page is None:
            page = await ctx.new_page()

        await page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(1500)

        # The calendar renders for guests too, keeping its normal title and
        # simply listing nothing — so a title check reports "0 events" instead
        # of a failure.
        # Signed-in state is read off the nav: a logout link exists only for a
        # real session. (M.cfg.userid is NOT usable here — this Moodle leaves it
        # undefined whether or not anyone is signed in; M.cfg.sesskey is set for
        # guests too, so it is no good either.)
        signed_in = await page.evaluate(
            """() => document.querySelectorAll('a[href*="login/logout.php"]').length > 0"""
        )
        if not signed_in:
            raise RuntimeError("Moodle login expired on CDP browser (no logout link in nav)")

        raw = await page.evaluate(
            r'''() => {
            const rows = [];
            const selectors = [
              '[data-region="event-item"]', '.event', '.event-card', '.calendar_event', 'li.event'
            ];
            let items = [];
            for (const s of selectors) {
              const f = [...document.querySelectorAll(s)];
              if (f.length) { items = f; break; }
            }
            for (const el of items) {
              const name = (el.querySelector('.eventname,h3,h4,a')?.textContent || '').trim();
              const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
              const link = el.querySelector('a[href]')?.href || '';
              if (name) rows.push({name, text, link});
            }
            // de-dup
            const seen = new Set();
            const out = [];
            for (const r of rows) {
              const k = `${r.name}|${r.link}`;
              if (seen.has(k)) continue;
              seen.add(k);
              out.push(r);
            }
            return out;
        }'''
        )

        now_utc = datetime.now(timezone.utc)
        events = []
        for e in raw:
            due_iso, due_dt = parse_due_from_text(e.get("text", ""))
            hours_left = None
            overdue = False
            due_in_2days = False
            if due_dt is not None:
                delta_h = (due_dt.astimezone(timezone.utc) - now_utc).total_seconds() / 3600
                hours_left = round(delta_h, 1)
                overdue = delta_h < 0
                due_in_2days = (0 <= delta_h <= 48)

            events.append(
                {
                    "name": e.get("name", ""),
                    "text": e.get("text", ""),
                    "link": e.get("link", ""),
                    "due_iso": due_iso,
                    "hours_left": hours_left,
                    "due_in_2days": due_in_2days,
                    "overdue": overdue,
                }
            )

        # load previous report for diff
        prev_events = []
        if Path(PREV).exists():
            try:
                prev_events = json.loads(Path(PREV).read_text(encoding="utf-8")).get("events", [])
            except Exception:
                prev_events = []
        elif Path(OUT).exists():
            try:
                prev_events = json.loads(Path(OUT).read_text(encoding="utf-8")).get("events", [])
            except Exception:
                prev_events = []

        added, changed = diff_events(prev_events, events)

        alerts = []
        for e in added:
            alerts.append({"type": "new_event", "event": e})
        for c in changed:
            alerts.append({"type": "due_changed", "before": c["before"], "after": c["after"]})
        for e in events:
            if e.get("due_in_2days") and not e.get("overdue"):
                alerts.append({"type": "due_48h", "event": e})

        report["events"] = events
        report["total"] = len(events)
        report["soon_48h"] = len([x for x in events if x.get("due_in_2days") and not x.get("overdue")])
        report["overdue"] = len([x for x in events if x.get("overdue")])
        report["changes"] = {
            "added_count": len(added),
            "changed_count": len(changed),
            "added": added,
            "changed": changed,
        }
        report["alerts"] = alerts

        # rotate only on success
        if Path(OUT).exists():
            try:
                Path(PREV).write_text(Path(OUT).read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                pass
        Path(OUT).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        await browser.close()

    print(f"TOTAL={report['total']}")
    print(f"SOON_48H={report['soon_48h']}")
    print(f"ADDED={report['changes']['added_count']}")
    print(f"CHANGED={report['changes']['changed_count']}")
    print(f"ALERTS={len(report['alerts'])}")


if __name__ == "__main__":
    asyncio.run(main())
