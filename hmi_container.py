# hmi_container.py —— TJC / Nextion `.HMI` 工程容器的读取（★自动探测目录起点）
# ============================================================================
# ★为什么单独抽这个文件（2026-09-30 实测，踩过）：
#   **目录起点不是固定值** ✗ —— 实测到至少三种：
#     · 新格式（魔数 `05 00 00 00`）                → 起点 **4**
#     · 旧格式（魔数 `1a 02 00 00 00`）              → 起点 **5**
#     · 编辑器直接保存的工程（魔数 `17 00 00 00`）    → 起点 **4**
#       （这种文件的**第一条目录项名字的首字节可能是 `0x00`** ⇒ 名字读出来是空的，
#         但 off/len 是好的 ⇒ **不能因为名字空就把这条丢掉** ✗ 否则整张目录会错位）
#   ⇒ **写死任何一个起点都会静默读错/漏条目** ✗
#     （原 `hmi_parse.py` 写死 `0x20` ⇒ 读新格式文件时**丢掉第一条 `main.HMI`** ✗✓）
#
# ★判据＝**连续性**（这个判据很好用 ✓）：
#   目录项里带着**显式**的数据偏移 ⇒ 正常情况下「前一项 off + len == 后一项 off」
#   把每个候选起点算一遍连续率，**挑最高的那个** ⇒ 起点就自动定下来了 ✓✓
#   （错位时连续率会掉到 0 ✗，正确时接近满分 ✓）
#
# 目录项 = 28 字节：`[名字 16B，\0 填充][数据偏移 4B 小端][数据长度 4B 小端][标志 4B]`
# ============================================================================
from __future__ import annotations

import struct

ENTRY = 28


def scan(data: bytes, start: int, maxn: int = 4000) -> list[dict]:
    """从 start 开始按 28B 步长读目录项（不做任何"名字空就跳过"的处理 ✓）"""
    ents = []
    for i in range(maxn):
        base = start + ENTRY * i
        e = data[base: base + ENTRY]
        if len(e) < ENTRY:
            break
        raw_name = e[:16]
        off, ln, flag = struct.unpack("<III", e[16:28])
        if off == 0 and ln == 0:          # 目录结束（全 0 项）
            break
        ents.append({
            "name": raw_name.split(b"\x00")[0].decode("latin1", "replace"),
            "raw_name": raw_name,
            "off": off, "len": ln, "flag": flag,
            "dir_off": base,
        })
    return ents


def contiguity(ents: list[dict]) -> tuple[int, int]:
    """连续性：前一项 off+len == 后一项 off 的条数 / 总数"""
    good = sum(1 for a, b in zip(ents, ents[1:]) if a["off"] + a["len"] == b["off"])
    return good, max(1, len(ents) - 1)


def detect_start(data: bytes, candidates=None) -> tuple[int, list[dict], int, int]:
    """挑最优目录起点。返回 (start, entries, good, total)"""
    if candidates is None:
        candidates = range(4, 40)          # 实测都在这一段里；再多也没意义（连续率会把它否掉）
    best = None
    for s in candidates:
        ents = scan(data, s)
        if len(ents) < 2:
            continue
        good, tot = contiguity(ents)
        score = (good / tot, len(ents))    # 先比连续率，再比条目数
        if best is None or score > best[0]:
            best = (score, s, ents, good, tot)
    if best is None:
        raise ValueError("目录解析失败：候选起点都读不出条目")
    _, s, ents, good, tot = best
    return s, ents, good, tot


def read(path: str, verbose: bool = False) -> dict:
    """读一个 .HMI：返回 {path, data, size, magic, dir_start, entries, contiguity}"""
    with open(path, "rb") as f:
        data = f.read()
    start, ents, good, tot = detect_start(data)
    info = {
        "path": path,
        "data": data,
        "size": len(data),
        "magic": data[:5].hex(" "),
        "dir_start": start,
        "entries": ents,
        "contiguity": {"good": good, "total": tot, "percent": round(100.0 * good / tot, 1)},
    }
    if verbose:
        print("  %s  %s  magic=%s  目录起点=%d  条目=%d  连续率=%d/%d (%.1f%%)"
              % (path, "{:,}B".format(len(data)), info["magic"], start,
                 len(ents), good, tot, info["contiguity"]["percent"]))
    return info


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        r = read(p, verbose=True)
        for e in r["entries"]:
            print("     %-18s off=%-10d len=%-9d flag=%d"
                  % (e["name"] or "(名字首字节为 0x00)", e["off"], e["len"], e["flag"]))
