# hmi_page.py —— 页面组装（含【控件表】★2026-09-26 挖出的关键结构）
# 页面文件 = [可变长头部 68+8N] + [页面块 att-28…] + [4B 00 分隔符] + [控件块 × N]
# 头部 = base(52B，抄空工程) + [4B 表长=4+8(N+1)=12+8N] + [4B 页面块长度]
#        + [(4B 控件偏移, 4B 控件长度) × N] + [4B 0, 4B 0 终止符]
#   · 第一个控件偏移 = 头部长度 + 页面块长度 + 4       （实测 36+701=737 ✓ 自洽）
#   · 头部 @12 的计数 = N                              （实测编辑器 3 控件时写 3 ✓）
#   · 头部前 4 字节是哈希，编辑器不校验 ⇒ 沿用原值 ✓
import struct

def build_page(blank_pa: bytes, page_block: bytes, comps: list) -> bytes:
    """按【权威对照】（2026-09-26 编辑器亲手保存版）精确组装：
       头长 = 68+12N；@4 总长；@8=56；@12=1+N；@56 表长=12(1+N)
       表内容(@60起) = [4B 页面块长+4][4B 0] + 每控件 [4B 相对偏移-60][4B 大小][4B 0]
    """
    assert blank_pa.find(b'att-') > 0, 'blank_pa 不对'
    N = len(comps)
    header_len = 68 + 12 * N
    base52 = bytearray(blank_pa[:52])
    header = base52 + b'\x00' * 4                       # @52 恒为 0
    header += struct.pack('<I', 12 * (1 + N))            # @56 表长
    header += struct.pack('<I', len(page_block) + 4)     # 页面块长 + 4
    header += struct.pack('<I', 0)
    off = header_len + len(page_block) + 4
    for c in comps:
        header += struct.pack('<III', off - 56, len(c), 0)   # 相对基准 = 表起点 @56 ✓（实测 793-56=737 ✓）
        off += len(c)
    assert len(header) == header_len, f'头长不符 {len(header)} vs {header_len}'
    hb = bytearray(header)
    struct.pack_into('<I', hb, 12, 1 + N)                # @12 = 1 + N
    struct.pack_into('<I', hb, 4, header_len + len(page_block) + 4 + sum(len(c) for c in comps))
    body = page_block + struct.pack('<I', 0) + b''.join(comps)
    return bytes(hb) + body

def parse_page_header(pa: bytes):
    """解出头部结构，用于自检"""
    i = pa.find(b'att-')
    if i < 0:
        return None
    hdr = pa[:i - 4]
    table_len = struct.unpack('<I', hdr[56:60])[0]
    page_field = struct.unpack('<I', hdr[60:64])[0]
    n_comp = (table_len // 12) - 1
    comps = []
    p = 68
    for k in range(max(0, n_comp)):
        rel, size, z = struct.unpack('<III', hdr[p:p+12]); comps.append((rel + 56, size, z)); p += 12
    cnt = struct.unpack('<I', hdr[12:16])[0]
    return {'header_len': len(hdr), 'table_len': table_len, 'page_field': page_field,
            'count@12': cnt, 'n_comp': n_comp, 'comps': comps,
            'total@4': struct.unpack('<I', hdr[4:8])[0]}
