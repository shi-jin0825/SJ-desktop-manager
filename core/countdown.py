# -*- coding: utf-8 -*-
"""倒数日计算（纯标准库 datetime）。

一条倒计时的存储结构（在 config.json 的 countdowns 里）：
    {"id": "cd...", "title": "考研", "date": "2027-12-20",
     "note": "加油", "repeat": true, "created": "2026-10-31"}

    date    目标日期（YYYY-MM-DD）
    repeat  是否每年循环（生日 / 纪念日等，年年都过）
    created 创建日期，用来算「已完成百分比」
"""
import datetime as dt

WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 日期分隔符：2026-12-20 / 2026/12/20 / 2026.12.20 / 2026年12月20日
_SEPS = ("-", "/", ".", "年", "月")


def today() -> dt.date:
    return dt.date.today()


def parse_date(text):
    """把文本解析成 date；无法解析（或日期非法）返回 None。"""
    if isinstance(text, dt.date):
        return text
    s = (text or "").strip()
    if not s:
        return None
    for sep in _SEPS:
        s = s.replace(sep, "-")
    s = s.rstrip("-日").strip()
    parts = [p for p in s.split("-") if p]
    if len(parts) != 3:
        return None
    try:
        y, m, d = (int(p) for p in parts)
        return dt.date(y, m, d)
    except (ValueError, TypeError):
        return None


def fmt_date(d) -> str:
    """date -> '2026-12-20'。"""
    return d.strftime("%Y-%m-%d") if isinstance(d, dt.date) else ""


def weekday_cn(d) -> str:
    """date -> '周六'。"""
    return WEEKDAY_CN[d.weekday()] if isinstance(d, dt.date) else ""


def next_target(target, ref=None, repeat: bool = False):
    """下一次「到达」的日期。

    repeat=False：就是目标日本身（过去也一样返回）。
    repeat=True ：把年份换到 ref 所在年份；若今年已过，就顺延到明年。
    """
    if not isinstance(target, dt.date):
        return None
    if not repeat:
        return target
    ref = ref or today()
    try:
        cand = target.replace(year=ref.year)
    except ValueError:                      # 2 月 29 日落在平年
        cand = target.replace(year=ref.year, day=28)
    if cand < ref:
        try:
            cand = cand.replace(year=cand.year + 1)
        except ValueError:
            cand = cand.replace(year=cand.year + 1, day=28)
    return cand


def days_until(target, ref=None) -> int:
    """距离目标日还有几天：>0 未来，0 就是今天，<0 已过去。"""
    if not isinstance(target, dt.date):
        return 0
    ref = ref or today()
    return (target - ref).days


def _shift_year(d, delta):
    """把日期的年份平移 delta 年；2 月 29 日落在平年时退到 28 日。"""
    try:
        return d.replace(year=d.year + delta)
    except ValueError:
        return d.replace(year=d.year + delta, day=28)


def progress(item, ref=None):
    """完成度（0.0 ~ 1.0）。

    普通倒计时：创建日 -> 目标日。
    每年循环的：上一次周年日 -> 下一次周年日（生日就永远在 0~100% 之间走）。
    区间异常时返回 None（页面就不画进度条）。
    """
    ref = ref or today()
    base = parse_date(item.get("date"))
    if not base:
        return None
    if item.get("repeat"):
        target = next_target(base, ref, True)
        start = _shift_year(target, -1)
        # 循环项的创建日期若晚于上一次周年日，就从创建日起算
        created = parse_date(item.get("created"))
        if created and created > start:
            start = created
    else:
        start = parse_date(item.get("created"))
        target = base
    if not start or not target or target <= start:
        return None
    total = (target - start).days
    done = (ref - start).days
    return max(0.0, min(1.0, done / total))


def describe(item, ref=None) -> dict:
    """把一条倒计时算成页面可以直接用的信息。

    返回 dict：
        days    剩余天数（未来为正；已过为负；今天为 0）
        state   'future' / 'today' / 'past'
        target  本次指向的日期（循环时是下一次）
        text    主文案，如「还有 42 天」「就是今天」「已过 3 天」
    """
    ref = ref or today()
    base = parse_date(item.get("date"))
    repeat = bool(item.get("repeat"))
    if base is None:
        return {"days": 0, "state": "invalid", "target": None, "text": "日期无效"}
    target = next_target(base, ref, repeat)
    days = days_until(target, ref)
    if days > 0:
        state, text = "future", f"还有 {days} 天"
    elif days == 0:
        state, text = "today", "就是今天"
    else:
        state, text = "past", f"已过 {-days} 天"
    return {"days": days, "state": state, "target": target, "text": text}


def sort_key(item, ref=None):
    """列表排序：还没到的按临近排前面，已过去的排中间，日期无效的垫底。"""
    ref = ref or today()
    info = describe(item, ref)
    if info["state"] == "invalid":
        return (2, 0, item.get("title", ""))
    d = info["days"]
    if d >= 0:
        return (0, d, item.get("title", ""))
    return (1, -d, item.get("title", ""))


def quick_date(days: int, ref=None):
    """相对今天 N 天后的日期（快捷按钮用）。"""
    ref = ref or today()
    return ref + dt.timedelta(days=days)


# ======================================================================
# 日程计划（时间管理页）
#
# 一条计划的存储结构（config.json 的 plans 里）：
#     {"id": "pl...", "title": "写周报", "date": "2026-11-07",
#      "note": "", "done": false, "done_at": "", "created": "2026-11-04"}
#
# date  计划日期（YYYY-MM-DD），空串 = 不限日期的待办
# done  是否已完成；done_at 记录勾选完成的日期（重做时清空）
# ======================================================================

def plan_describe(item, ref=None) -> dict:
    """把一条计划算成页面直接可用的信息。

    返回 dict：
        state   'future' / 'today' / 'past' / 'nodate'
        target  计划日期（nodate 时为 None）
        text    主文案：「还有 N 天」「今天要做」「已过 N 天」「随时可做」
    """
    ref = ref or today()
    base = parse_date(item.get("date"))
    if base is None:
        return {"state": "nodate", "target": None, "text": "随时可做"}
    days = days_until(base, ref)
    if days > 0:
        state, text = "future", f"还有 {days} 天"
    elif days == 0:
        state, text = "today", "今天要做"
    else:
        state, text = "past", f"已过 {-days} 天"
    return {"state": state, "target": base, "text": text}


def plan_sort_key(item, ref=None):
    """列表排序：未完成的在前（按日期临近，无日期排最后），完成的垫底。

    返回的元组可直接传给 sorted 的 key。
    """
    ref = ref or today()
    if item.get("done"):
        return (1, item.get("done_at", ""), item.get("title", ""))
    info = plan_describe(item, ref)
    if info["state"] == "nodate":
        return (0, "9999-12-31", item.get("title", ""))
    return (0, fmt_date(info["target"]), item.get("title", ""))
