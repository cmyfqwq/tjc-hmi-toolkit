# hmi_parse.py —— TJC .HMI 容器 + .pa 页面块 的正式解析器（2026-09-26；2026-09-30 修目录起点）
# 容器：目录项 28B：[名16B][偏移4B LE][长度4B LE][标志4B]
#   ★目录起点**不是固定值** ✗ —— 实测 4（新格式）/ 5（旧格式），详见 hmi_container.py；
#     写死任一个都会**静默漏条目** ✗（本文件原来写死 0x20 ⇒ 新格式会丢第一条 main.HMI ✗）
# 页面：68B 文件头 + TLV 序列；TLV = [4B 总长][载荷]，载荷 = 属性名 + 值
#   · 属性块：载荷里先是明文属性名，值的小端数值写在载荷末尾（字符串也是末尾）
#   · 组件块：以 att-N 开头，其后属性属于该组件，直到下一个 att-
#   · 事件块：codesdown-N / codesup-N / codesload-N / codesloadend-N / codesunload-N / codestimer-N
#             —— 标记块本身没有值，紧跟着的"下一个块"其名字就是代码文本本身
import struct, re, sys, os

ATTR_RE = re.compile(rb'([\x20-\x7e]{1,28})')
KNOWN_PREFIX = (b'att-', b'codes')

def parse_container(path):
    """★2026-09-30 修：改用 `hmi_container` 的**自动探测**（按连续性挑目录起点 ✓）
    原来这里写死 `off = 0x20` ✗ —— 读新格式（魔数 `05 00 00 00`）的文件时
    **会丢掉第一条目录项 `main.HMI`** ✗✓；而且 `if not name: continue` 在
    "首条目名字首字节是 0x00"的文件上会把整张目录读错位 ✗。"""
    import hmi_container
    r = hmi_container.read(path)
    return r['data'], r['entries']

def tlv_iter(blob, start):
    pos = start
    while pos + 4 <= len(blob):
        total = struct.unpack('<I', blob[pos:pos + 4])[0]
        if total == 0 or total > 65536 or pos + 4 + total > len(blob):
            break
        payload = blob[pos + 4: pos + 4 + total]
        yield pos, total, payload
        pos += 4 + total

def split_name_value(payload):
    m = ATTR_RE.match(payload)
    if not m:
        return None, payload
    name = m.group(1)
    return name, payload[len(name):]

def val_int(val):
    return int.from_bytes(val[-4:], 'little') if len(val) >= 4 else None

def val_str(val):
    # 去掉末尾的 4 字节小端数值/填充，取可打印部分
    raw = val[:-4] if len(val) >= 4 else val
    raw = raw.rstrip(b'\0')
    try:
        return raw.decode('gbk', 'replace')
    except Exception:
        return ''

def parse_page(blob):
    i = blob.find(b'att-')
    hdr_end = max(0, i - 4) if i >= 0 else 0
    out = {'header_len': hdr_end, 'header_ascii': ''.join(chr(c) if 32 <= c < 127 else '.' for c in blob[:hdr_end]),
           'items': [], 'codes': []}
    cur = None
    pending_code = None
    for pos, total, payload in tlv_iter(blob, hdr_end):
        name, val = split_name_value(payload)
        if name is None:
            continue
        nm = name.decode('ascii', 'replace')
        if nm.startswith('att-'):
            cur = {'att': nm, 'attrs': {}, 'pos': pos}
            out['items'].append(cur)
            continue
        if nm.startswith('codes'):
            # 标记块：无值；紧随其后的块名字就是代码
            pending_code = {'marker': nm, 'code': ''}
            out['codes'].append(pending_code)
            continue
        if pending_code is not None and not val and nm.strip():
            pending_code['code'] = nm
            pending_code = None
            continue
        if cur is None:
            continue
        cur['attrs'][nm] = {'int': val_int(val), 'str': val_str(val), 'raw': val}
    return out

def summarize(path, show_items=40):
    data = open(path, 'rb').read()
    if data[:2] == b'\x1a\x02' or b'main.HMI' in data[:64] or True:
        pg = parse_page(data)
        print(f"\n=== {os.path.basename(path)}  {len(data):,}B  header={pg['header_len']}B ===")
        print("  hdr:", pg['header_ascii'][:60])
        for it in pg['items'][:show_items]:
            a = it['attrs']
            def gi(k): return a.get(k, {}).get('int')
            def gs(k): return (a.get(k, {}).get('str') or '').strip()
            print(f"  {it['att']:8s} type={gi('type')} id={gi('id')} name='{gs('objname')}' x={gi('x')} y={gi('y')} w={gi('w')} h={gi('h')} bco={gi('bco')} pco={gi('pco')} font={gi('font')} txt='{gs('txt')}'")
        if pg['codes']:
            print("  --- 事件代码 ---")
            for c in pg['codes']:
                if c['code']:
                    print(f"    {c['marker']:16s} -> {c['code']!r}")
    return pg

if __name__ == '__main__':
    for p in sys.argv[1:]:
        try:
            summarize(p)
        except Exception as ex:
            print(f"  FAIL {p}: {ex}")
