#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hmi_drop_page.py —— 从 .HMI 容器里删掉一个页面条目

原理（关键 ✓）：容器 = [magic][28B×N 目录项][数据区]
  · 每个目录项带【显式】的数据偏移 ⇒ 删掉一项后：
      ①目录区少 28B ⇒ 把数据区整体前移 28B
      ②所有目录项的偏移 -= 28（对在删除点之后的项）✓
  · ★【完全不碰任何页面内容】⇒ 不会触发"页面头 @0 校验"导致的「加载页面失败」✓✓
    （这正是程序化编辑 .HMI 唯一安全的操作：动结构、不动内容 ✓）

用法:
    python hmi_drop_page.py <in.HMI> <out.HMI> --page 5
    python hmi_drop_page.py ui6.HMI ui6_5p.HMI --page 5 --dry-run
"""
from __future__ import annotations
import argparse, struct, sys


def read_container(path):
    data = open(path, "rb").read()
    magic_len = 4
    if data[:5] == b"\x1a\x02\x00\x00\x00":
        magic_len = 5
    ents = []
    for i in range(4000):
        off = magic_len + 28 * i
        e = data[off: off + 28]
        if len(e) < 28:
            break
        name = e[:16].split(b"\x00")[0]
        doff, dlen, flag = struct.unpack("<III", e[16:28])
        if doff == 0 and dlen == 0:
            break
        ents.append({"name": name, "off": doff, "len": dlen, "flag": flag,
                     "dir_off": off, "raw": bytearray(e)})
    return {"data": data, "magic_len": magic_len, "entries": ents}


def main():
    ap = argparse.ArgumentParser(description="从 .HMI 删掉一个页面条目")
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--page", required=True, help="页面号，如 5")
    ap.add_argument("--force", action="store_true", help="即使该页非 0 字节也删（空页仍有 ~769B 头部 ✓）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    c = read_container(a.src)
    data = c["data"]; ml = c["magic_len"]; ents = c["entries"]
    target = (a.page + ".pa").encode()
    idx = next((i for i, e in enumerate(ents) if e["name"] == target), None)
    if idx is None:
        print(f"✗ 容器里没有 {target.decode()}；现有: " +
              ", ".join(e["name"].decode('latin1') for e in ents))
        return 2

    victim = ents[idx]
    if victim["len"] != 0 and not a.force:
        print(f"⚠ {target.decode()} 不是空页（{victim['len']}B）—— 本次【已中止】"
              f"（确认要删就加 --force ✓；空页也有约 769B 头部属正常 ✓）")
        return 3
    print(f"容器 {len(data):,}B  目录项 {len(ents)} 个")
    print(f"将删除 {target.decode()}（off={victim['off']:,} len={victim['len']:,}）")
    for e in ents:
        mark = "  ← 删除" if e is victim else ""
        print(f"   {e['name'].decode('latin1'):12s} off={e['off']:>10,} len={e['len']:>10,}{mark}")

    if a.dry_run:
        print("（dry-run，未写文件）")
        return 0

    keep = [e for i, e in enumerate(ents) if i != idx]
    body_start = ml + 28 * len(ents)
    new_body_start = ml + 28 * len(keep)
    shift = 28                       # 目录区少一项 ⇒ 数据区前移 28B

    out = bytearray(data[:ml])
    for e in keep:
        raw = bytearray(e["raw"])
        new_off = e["off"] - shift if e["off"] > victim["off"] else e["off"]
        struct.pack_into("<III", raw, 16, new_off, e["len"], e["flag"])
        out += raw
    # 数据区：把被删页之后的内容前移 28B
    out += data[body_start: victim["off"]]
    out += data[victim["off"] + victim["len"]:]

    open(a.dst, "wb").write(bytes(out))
    print(f"✓ 已写出 {a.dst}  ({len(data):,}B → {len(out):,}B，少 {len(data)-len(out):,}B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
