# hmi_comp.py —— 控件块编解码【修正版】(2026-09-26)
# 三条铁律（由往返测试逼出来 ✓）：
#   ① 写值必须沿用模板的"有效字节宽度"（去前导零后的长度），不能只写最小字节
#      —— 例：w=100 模板写的是 2 字节 `64 00`；只写 1 字节 `64` 再左补零 ⇒ 会变成 0x6400=25600 ✗
#   ② 事件块结构 = [marker 块] + [代码块]，代码块的"名字"就是代码文本；
#      代码为空时那个块就是 `00 00 00 00`（total=0）—— 它同样要被消费掉 ✗ 不能当成普通空块
#   ③ 每条控件记录尾部还有 4 字节 `00 00 00 00`；记录的"大小"= 全部块 + 这 4 字节
import struct, re

NAME_RE = re.compile(rb'([\x20-\x7e]{1,40})')

def u32(b):
    return struct.unpack('<I', b[:4])[0]

def tlv(name: bytes, value: bytes, slot: int):
    v = value.rjust(slot, b'\x00') if len(value) < slot else value
    return struct.pack('<I', len(name) + len(v)) + name + v

def parse_comp(block: bytes):
    """返回 (att, items, codes)：items = [(name(bytes), val(bytes))]（不含 att 与事件），codes = [(marker, codebytes)]"""
    att = None
    items, codes = [], []
    pos = 0
    while pos + 4 <= len(block):
        total = u32(block[pos:pos+4])
        if total == 0:
            break                                  # 记录尾（4 字节 0）
        if total > 8192 or pos + 4 + total > len(block):
            break
        pay = block[pos+4:pos+4+total]
        m = NAME_RE.match(pay)
        if not m:
            break
        name = m.group(1)
        val = pay[len(name):]
        if att is None:
            att = name
            pos += 4 + total
            continue
        if name.startswith(b'codes'):
            # ★事件规则（往返测试逼出来的）：
            #   看紧随其后的那块：① total==0 ⇒ 空代码，消费 4 字节
            #                     ② 它的名字也以 codes 开头 ⇒ 空代码，且【不消费】（那是下一个 marker）
            #                     ③ 否则 ⇒ 它的名字就是代码文本，消费整块
            nt = u32(block[pos+4+total:pos+8+total]) if pos + 8 + total <= len(block) else 0
            if nt == 0:
                codes.append((name.decode('ascii', 'replace'), b''))
                pos += 4 + total + 4
                continue
            npay = block[pos+8+total: pos+8+total+nt]
            m2 = NAME_RE.match(npay)
            nxt_name = m2.group(1) if m2 else b''
            if nxt_name.startswith(b'codes'):
                codes.append((name.decode('ascii', 'replace'), b''))
                pos += 4 + total
                continue
            codes.append((name.decode('ascii', 'replace'), nxt_name))
            pos += 8 + total + nt
            continue
        items.append((name, val))
        pos += 4 + total
    return att, items, codes

def encode_like(v, width: int) -> bytes:
    if isinstance(v, str):
        return v.encode('gbk')
    if v == 0:
        return b''
    n = width if width > 0 else 1
    while v >= (1 << (8 * n)):
        n += 1
    return v.to_bytes(n, 'little')

def clone_comp(tpl: bytes, values: dict, codes: dict = None, att: str = None, att_id: int = None) -> bytes:
    """tpl: 权威控件块（含尾部 4 字节）; values: {名: int|str}; codes: {marker名: 代码文本}"""
    a, items, tpl_codes = parse_comp(tpl)
    if att is None:
        att = a.decode()
    if att_id is None:
        m = re.match(r'att-(\d+)', att)
        att_id = int(m.group(1)) if m else 40
    out = bytearray(tlv(b'att-%d' % att_id, b'', 0))
    for name, val in items:
        nm = name.decode('ascii', 'replace')
        slot = len(val)
        width = len(val.lstrip(b'\x00'))
        if nm in values:
            b = encode_like(values[nm], width)
            if len(b) > slot:
                slot = len(b)
            out += tlv(name, b, slot)
        else:
            out += tlv(name, val, slot)            # 未指定 ⇒ 原样保留（含原宽度 ✓）
    # ★事件：以【模板的 marker 顺序】为准逐个写，保证一个 marker 都不丢 ✓
    #   （踩过的坑：只传 codesdown-0 ⇒ 模板里的 codesup-0 被吞掉 ⇒ 记录少字节 ⇒ 编辑器"加载页面失败" ✗）
    cmap = dict(codes or {})
    for marker, tcode in tpl_codes:
        out += tlv(marker.encode(), b'', 0)
        code = cmap.pop(marker, tcode)
        if code:
            cb = code.encode('gbk') if isinstance(code, str) else bytes(code)
            out += tlv(cb, b'', len(cb))
    for marker, code in cmap.items():                  # 模板里没有的（新增事件）
        out += tlv(marker.encode(), b'', 0)
        if code:
            cb = code.encode('gbk') if isinstance(code, str) else bytes(code)
            out += tlv(cb, b'', len(cb))
    return bytes(out) + b'\x00\x00\x00\x00'        # ★记录尾
