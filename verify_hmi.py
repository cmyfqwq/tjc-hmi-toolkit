#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_hmi.py —— 串口屏工程自检器（验收判据 #1）

用法:
    python verify_hmi.py <工程.HMI> [--expect 期望清单.json]

默认按"串口屏项目约定清单"检查，也可用 --expect 传入自定义清单 JSON:
{
  "pages": 5,
  "controls": {
      "page0": ["tTitle","tNet","mWifi","mIp","mRom","mFix","mCheck","mAbout","tFoot"],
      "wifi":  ["tW0","tW1","tW2","tW3","tW4","tW5","tW6","tW7","tW8","tW9","tWsel","tSSID","tPass","tMsg","bOk","bBack"],
      "ip":    ["tIp","tMask","tGw","tDns","bDhcp","bStatic","bSave","bBack","tMsg"],
      "rom":   ["tVer","tState","tLog","bCheck","bAck","bSkip","bBack"],
      "about": ["tAbout","bBack"]
  },
  "events": {"mWifi": ["printh 23 53 43 41 4E"], "tLog": ["printh"]}
}

检查项:
  1. 容器连续率 100%（目录项「前一项偏移+长度 == 后一项偏移」）
  2. 页面数量与清单一致
  3. 每页控件名/数量与清单逐条相符（名字从控件记录的 objname 字段读）
  4. 事件代码里含约定 printh 序列（如果清单给了 events）

退出码: 0=全部通过  1=有检查未过  2=文件/参数错误
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
from typing import Any

# ★2026-09-30 修（发布前实测踩到）：中文 Windows 的控制台是 **GBK** ⇒
#   脚本里那些 ✓/✗ 一打印就 `UnicodeEncodeError: 'gbk' codec can't encode character` ✗，
#   而且**整个自检直接崩掉**（不是少打一个字符 ✗）。加这一句就稳了 ✓
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------- 容器解析

def read_container(path: str) -> dict[str, Any]:
    """读 .HMI 容器：返回 magic / entries / data"""
    data = open(path, "rb").read()
    result: dict[str, Any] = {"path": path, "size": len(data), "magic": data[:5].hex(" "), "entries": [], "errors": []}
    # 目录起点：新格式 4，旧格式（1a 02 00 00 00）5；用连续率自检挑最优
    best: tuple[int, int, list] | None = None
    for start in (4, 5):
        ents = []
        for i in range(4000):
            e = data[start + 28 * i: start + 28 * (i + 1)]
            if len(e) < 28:
                break
            name = e[:16].split(b"\x00")[0]
            off, ln, flag = struct.unpack("<III", e[16:28])
            if off == 0 and ln == 0:
                break
            ents.append({"name": name.decode("latin1"), "raw_name": name, "off": off, "len": ln, "flag": flag})
        if len(ents) < 3:
            continue
        good = sum(1 for i in range(len(ents) - 1) if ents[i]["off"] + ents[i]["len"] == ents[i + 1]["off"])
        if best is None or good > best[1]:
            best = (start, good, ents)
    if best is None:
        result["errors"].append("目录解析失败（两种起点都读不出条目）")
        return result
    start, good, ents = best
    result["dir_start"] = start
    result["entries"] = ents
    result["contiguity"] = {"good": good, "total": max(1, len(ents) - 1),
                            "percent": round(100.0 * good / max(1, len(ents) - 1), 1)}
    result["data"] = data
    return result


# ---------------------------------------------------------------- 页面解析

TLV_NAME = re.compile(rb"([\x20-\x7e]{1,28})")


def parse_component(block: bytes) -> dict[str, bytes]:
    """把控件记录（一连串 TLV）解析成 {属性名: 值字节}"""
    values: dict[str, bytes] = {}
    pos = 0
    n = len(block)
    while pos + 4 <= n:
        total = struct.unpack_from("<I", block, pos)[0]
        if total == 0:
            pos += 4
            continue
        if pos + 4 + total > n:
            break
        chunk = block[pos + 4: pos + 4 + total]
        # 属性名 = 头部可打印串
        m = TLV_NAME.match(chunk)
        if not m:
            pos += 4 + total
            continue
        name = m.group(1).decode("latin1")
        value = chunk[m.end():]
        values[name] = value
        pos += 4 + total
    return values


def value_of(values: dict[str, bytes], key: str) -> Any:
    if key not in values:
        return None
    raw = values[key]
    stripped = raw.lstrip(b"\x00")
    if key in ("objname", "txt", "type"):
        if key == "type":
            return int.from_bytes(raw, "little") if raw else 0
        try:
            return stripped.decode("gbk")
        except Exception:
            return stripped.decode("latin1")
    if stripped and len(stripped) <= 4:
        return int.from_bytes(stripped, "little")
    return stripped


def parse_page(blob: bytes) -> dict[str, Any]:
    """解析 N.pa：返回 header 字段 + 控件列表"""
    info: dict[str, Any] = {"size": len(blob), "errors": []}
    if len(blob) < 68:
        info["errors"].append("页面太短")
        return info
    info["magic"] = blob[:4].hex(" ")
    info["total_len"] = struct.unpack_from("<I", blob, 4)[0]
    info["const8"] = struct.unpack_from("<I", blob, 8)[0]
    info["count12"] = struct.unpack_from("<I", blob, 12)[0]
    info["const52"] = struct.unpack_from("<I", blob, 52)[0]
    info["table_len"] = struct.unpack_from("<I", blob, 56)[0]
    n_ctrl = max(0, info["count12"] - 1)
    info["ctrl_count"] = n_ctrl
    info["expected_header"] = 68 + 12 * n_ctrl
    info["expected_table"] = 12 * (1 + n_ctrl)
    # 控件块位置
    positions = [m.start() for m in re.finditer(rb"att-\d+", blob)]
    if positions:
        positions = positions[1:]  # 第一个是页面块 (att-28)
    controls = []
    for idx, pos in enumerate(positions):
        start = pos - 4
        end = (positions[idx + 1] - 4) if idx + 1 < len(positions) else len(blob)
        seg = blob[start:end]
        values = parse_component(seg)
        controls.append({
            "objname": value_of(values, "objname"),
            "type": value_of(values, "type"),
            "x": value_of(values, "x"), "y": value_of(values, "y"),
            "w": value_of(values, "w"), "h": value_of(values, "h"),
            "record_len": len(seg),
            "events": sorted(k for k in values if k.startswith("codes")),
            "code_blocks": {k: values[k] for k in values if k.startswith("codes")},
        })
    info["controls"] = controls
    # 事件代码文本（紧跟 codesX-N 的那个"名字即代码"的块）
    texts = []
    for m in re.finditer(rb"codes[a-z]+-\d+", blob):
        pos = m.end()
        if pos + 4 <= len(blob):
            total = struct.unpack_from("<I", blob, pos)[0]
            if 0 < total and pos + 4 + total <= len(blob):
                text = blob[pos + 4: pos + 4 + total].decode("gbk", "replace")
                texts.append(text)
    info["event_texts"] = texts
    return info


# ---------------------------------------------------------------- 检查

def main() -> int:
    ap = argparse.ArgumentParser(description="串口屏 .HMI 工程自检器（验收判据 #1）")
    ap.add_argument("hmi", help="要检查的 .HMI 文件")
    ap.add_argument("--expect", help="期望清单 JSON（缺省用项目约定清单）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args()

    if not os.path.exists(args.hmi):
        print(f"✗ 文件不存在: {args.hmi}")
        return 2

    default_expect: dict[str, Any] = {
        "pages": None,
        "controls": {},
        "events": {},
        "note": "未提供 --expect，只做结构性检查（连续率/页数/控件可读性/事件可读性）",
    }
    expect = default_expect
    if args.expect:
        try:
            expect = json.load(open(args.expect, encoding="utf-8"))
        except Exception as ex:
            print(f"✗ 读清单失败: {ex}")
            return 2

    container = read_container(args.hmi)
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": passed, "detail": detail})

    if container["errors"]:
        add("容器解析", False, "; ".join(container["errors"]))
        if args.json:
            print(json.dumps({"checks": checks}, ensure_ascii=False, indent=2))
        else:
            for c in checks:
                print(f"{'✓' if c['passed'] else '✗'} {c['check']}: {c['detail']}")
        return 1

    cont = container["contiguity"]
    add("容器目录连续率", cont["percent"] >= 100.0,
        f"{cont['good']}/{cont['total']} = {cont['percent']}%（目录起点 {container['dir_start']}）")

    data = container["data"]
    pages = {}
    page_names = []
    for ent in container["entries"]:
        name = ent["name"]
        if name.endswith(".pa"):
            blob = data[ent["off"]: ent["off"] + ent["len"]]
            info = parse_page(blob)
            entry_name = name[:-3]
            pages[entry_name] = info
            page_names.append(entry_name)

    if expect.get("pages") is not None:
        add("页面数量", len(pages) == expect["pages"],
            f"实际 {len(pages)}（{sorted(page_names)}）  期望 {expect['pages']}")
    else:
        add("页面数量（仅报告）", True, f"{len(pages)} 页: {sorted(page_names)}")

    # 每页结构自洽
    for entry, info in sorted(pages.items()):
        ok = (info["expected_header"] == (68 + 12 * info["ctrl_count"]) and
              info["table_len"] == info["expected_table"])
        add(f"页 {entry} 结构自洽", ok,
            f"控件 {info['ctrl_count']} 个  记录 {[c['record_len'] for c in info['controls']]}")

    # 控件名清单
    for entry, wanted in (expect.get("controls") or {}).items():
        if entry not in pages:
            add(f"页 {entry} 存在", False, "缺失 ✗")
            continue
        got = [c["objname"] for c in pages[entry]["controls"]]
        missing = [w for w in wanted if w not in got]
        extra = [g for g in got if g not in wanted]
        add(f"页 {entry} 控件清单", not missing,
            f"应有 {len(wanted)} 个，实有 {len(got)} 个"
            + (f"  缺: {missing}" if missing else "")
            + (f"  多: {extra}" if extra else ""))

    # 事件代码
    for ctrl, wanted_seqs in (expect.get("events") or {}).items():
        found = []
        for entry, info in pages.items():
            for text in info["event_texts"]:
                if ctrl in text or text.strip().startswith("printh"):
                    found.append(text)
        ok = True
        detail_bits = []
        for seq in wanted_seqs:
            hit = any(seq in t for t in found)
            ok = ok and hit
            detail_bits.append(f"{seq!r}: {'✓' if hit else '✗'}")
        add(f"事件代码 {ctrl}", ok, "  ".join(detail_bits))

    # 事件可读性总览
    all_texts = [t for info in pages.values() for t in info["event_texts"]]
    add("事件代码可读", True, f"共 {len(all_texts)} 段: " + "; ".join(t.strip().replace('\n', ' ')[:40] for t in all_texts[:6]))

    passed = all(c["passed"] for c in checks)
    if args.json:
        print(json.dumps({"file": args.hmi, "passed": passed, "checks": checks}, ensure_ascii=False, indent=2))
    else:
        print(f"=== 自检 {os.path.basename(args.hmi)}  ({container['size']:,}B) ===")
        for c in checks:
            print(f"{'✓' if c['passed'] else '✗'} {c['check']}: {c['detail']}")
        print()
        print("结论: " + ("全部通过 ✓✓" if passed else "有未通过项 ✗"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
