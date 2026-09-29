#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hmi_gen.py —— 串口屏 .HMI 工程「控件批量生成器」（逆向路线）

用途：往指定页面里批量克隆控件（默认克隆该页第 1 个控件的字节块），
      改掉 objname / x / y / w / h / txt，并修好所有长度字段与容器偏移。
      容器【无校验和】⇒ 可以自由重打包（已实测 ✓）。

用法:
    python hmi_gen.py <in.HMI> <out.HMI> --page 0 --spec spec.json
    python hmi_gen.py ui6.HMI ui7.HMI --page 0 --spec spec.json --dry-run

spec.json 例:
{
  "template": "t0",              # 以哪个控件为模板（名字）
  "new": [
    {"name": "mWifi", "x": 16,  "y": 80,  "w": 100, "h": 30, "txt": "WiFi"},
    {"name": "mIp",   "x": 272, "y": 80,  "w": 100, "h": 30, "txt": "IP"}
  ],
  "delete": ["t5"]               # 可选：删掉这些控件
}

原理（2026-09-27 实测确认）:
  · 页面文件 `N.pa` = 68 字节头 + 控件块序列；控件块以 6 字节 `att-<id>` 开头
  · 块边界 = `att` 位置 − 4  ..  下一个 `att` 位置 − 4（最后一块到文件尾）
  · 块内每个属性 = [4B total][name][补 0][值在尾部]，total = len(name)+len(值)
  · ★ 块长随值宽度变化 ⇒ 必须重算：页面头 @4 总长 / @56 表长(12×(1+N)) / 容器目录项长度与后续偏移
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys

ATTR_RE = re.compile(rb"([\x20-\x7e]{1,28})")


# ---------------------------------------------------------------- 容器读写

def read_container(path):
    data = open(path, "rb").read()
    start = 4
    if data[:5] == b"\x1a\x02\x00\x00\x00":
        start = 5
    ents = []
    for i in range(4000):
        e = data[start + 28 * i: start + 28 * (i + 1)]
        if len(e) < 28:
            break
        name = e[:16].split(b"\x00")[0]
        off, ln, fl = struct.unpack("<III", e[16:28])
        if off == 0 and ln == 0:
            break
        ents.append({"name": name, "off": off, "len": ln, "flag": fl, "dir_off": start + 28 * i})
    return {"data": data, "dir_start": start, "entries": ents}


def find_entry(container, name: bytes):
    for e in container["entries"]:
        if e["name"] == name:
            return e
    return None


# ---------------------------------------------------------------- 控件块

def split_attrs(block: bytes):
    """把控件块拆成 [前缀(att-N 那 4+6 字节)] + [(name, value_bytes)]"""
    # 块头：4 字节（对齐/未知）+ "att-N\0..."（6 字节可见）
    m = re.match(rb".{0,4}att-\d+", block)
    head_len = m.end() if m else 4
    head = block[:head_len]
    off = head_len
    attrs = []
    while off + 4 <= len(block):
        total = struct.unpack_from("<I", block, off)[0]
        if total == 0 or off + 4 + total > len(block):
            break
        chunk = block[off + 4: off + 4 + total]
        mm = ATTR_RE.match(chunk)
        if not mm:
            break
        name = mm.group(1)
        value = chunk[mm.end():]
        attrs.append((name, value, off))
        off += 4 + total
    tail = block[off:]
    return head, attrs, tail


def encode_attr(name: bytes, value: bytes) -> bytes:
    total = len(name) + len(value)
    return struct.pack("<I", total) + name + value


def set_attr(attrs, key: bytes, newvalue: bytes):
    for i, (name, value, off) in enumerate(attrs):
        if name == key:
            attrs[i] = (name, newvalue, off)
            return True
    return False


def get_attr(attrs, key: bytes):
    for name, value, off in attrs:
        if name == key:
            return value
    return None


def num_value(n: int) -> bytes:
    """数值按"去前导零"的最短小端写（实测规则 ✓）"""
    if n == 0:
        return b"\x00"
    b = n.to_bytes((n.bit_length() + 7) // 8, "little")
    return b.lstrip(b"\x00") or b"\x00"


def rebuild_block(head, attrs, tail):
    out = bytearray(head)
    for name, value, _ in attrs:
        out += encode_attr(name, value)
    out += tail
    return bytes(out)


# ---------------------------------------------------------------- 页面

def parse_page_blocks(blob: bytes):
    """返回 (头 68 字节, [每个控件的原始块])"""
    positions = [m.start() for m in re.finditer(rb"att-\d+", blob)]
    if len(positions) < 2:
        return blob[:68], []
    blocks = []
    for i in range(1, len(positions)):
        start = positions[i] - 4
        end = (positions[i + 1] - 4) if i + 1 < len(positions) else len(blob)
        blocks.append(blob[start:end])
    return blob[:68], blocks


def build_page(header: bytearray, blocks):
    body = b"".join(blocks)
    page = bytearray(header) + body
    n = len(blocks)
    struct.pack_into("<I", page, 4, len(page))        # @4 = 页面总长
    struct.pack_into("<I", page, 12, n + 1)           # @12 = 1 + 控件数
    struct.pack_into("<I", page, 56, 12 * (1 + n))    # @56 = 12 × (1+N)
    return bytes(page)


def main():
    ap = argparse.ArgumentParser(description="串口屏 .HMI 控件批量生成器")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--page", default="0")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    spec = json.load(open(args.spec, encoding="utf-8"))
    container = read_container(args.src)
    page_name = (args.page + ".pa").encode()
    pe = find_entry(container, page_name)
    if pe is None:
        print(f"✗ 容器里没有 {page_name.decode()}")
        return 2
    blob = container["data"][pe["off"]: pe["off"] + pe["len"]]
    header, blocks = parse_page_blocks(blob)
    print(f"页面 {args.page}: {len(blob):,}B  控件块 {len(blocks)} 个")

    # 建立名字 → 索引
    names = []
    for b in blocks:
        _, attrs, _ = split_attrs(b)
        nm = get_attr(attrs, b"objname") or b"?"
        names.append(nm.lstrip(b"\x00").decode("latin1"))
    print("  现有控件:", names)

    tmpl_name = spec.get("template") or (names[0] if names else None)
    if tmpl_name not in names:
        print(f"✗ 模板控件 {tmpl_name} 不在本页")
        return 2
    tmpl_block = blocks[names.index(tmpl_name)]
    t_head, t_attrs, t_tail = split_attrs(tmpl_block)
    print(f"  模板 = {tmpl_name}（{len(tmpl_block)}B，{len(t_attrs)} 个属性）")

    new_blocks = list(blocks)
    # 删除
    for d in spec.get("delete", []):
        if d in names:
            new_blocks.pop(names.index(d))
            print(f"  删除 {d}")
    # 新增
    for item in spec.get("new", []):
        head = bytearray(t_head)
        attrs = [(n, v, o) for (n, v, o) in t_attrs]
        set_attr(attrs, b"objname", item["name"].encode())
        for k in ("x", "y", "w", "h"):
            if k in item:
                set_attr(attrs, k.encode(), num_value(int(item[k])))
        if "txt" in item:
            set_attr(attrs, b"txt", item["txt"].encode("gbk", "replace"))
        blk = rebuild_block(bytes(head), attrs, t_tail)
        new_blocks.append(blk)
        print(f"  + {item['name']:<10} ({len(blk)}B)")
    # 重新生成这一页
    body = b"".join(new_blocks)
    # 新块头 att-N 需要重编号（顺序即 id）
    fixed = []
    idx = 0
    for blk in new_blocks:
        h, a, t = split_attrs(blk)
        hid = re.search(rb"att-(\d+)", h)
        if hid:
            h = h[:hid.start(1)] + str(idx).encode() + h[hid.end(1):]
        # 保持头部总长不变（数字位数可能变）—— 若位数变了，用 0 填充补齐
        fixed.append(rebuild_block(h, a, t))
        idx += 1
    page_new = build_page(bytearray(header), fixed)
    print(f"  新页面 {len(blob):,}B → {len(page_new):,}B")

    if args.dry_run:
        print("（dry-run，未写文件）")
        return 0

    # 重打包容器：替换该页数据，修所有目录项的偏移
    out = bytearray(container["data"])
    delta = len(page_new) - pe["len"]
    out[pe["off"]: pe["off"] + pe["len"]] = page_new
    for e in container["entries"]:
        if e["off"] > pe["off"]:
            e["off"] += delta
        if e["name"] == page_name:
            e["len"] = len(page_new)
    for e in container["entries"]:
        struct.pack_into("<III", out, e["dir_off"] + 16, e["off"], e["len"], e["flag"])
    open(args.dst, "wb").write(bytes(out))
    print(f"✓ 已写出 {args.dst}  ({len(out):,}B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
