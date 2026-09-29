# hmi_templates.py —— 用正确的"去前导零"解码，导出 按钮/文本/页面 三种块的逐字节模板
import struct, re, glob, os, json

ATT = re.compile(rb"([\x20-\x7e]{1,28})")

def decode_val(val):
    """值写在载荷尾部、前面补 0 ⇒ 去掉前导 0 后剩下的就是值"""
    v = val.lstrip(b'\x00')
    if not v:
        return ('int', 0)
    if len(v) <= 4:
        return ('int', int.from_bytes(v, 'little'))
    try:
        return ('str', v.decode('gbk'))
    except Exception:
        return ('int', int.from_bytes(v[-4:], 'little'))

def parse_blocks(blob):
    out = []
    for m in re.finditer(rb"att-\d+", blob):
        st = m.start() - 4
        pos = st
        attrs = {}
        for _ in range(80):
            if pos + 4 > len(blob):
                break
            total = struct.unpack('<I', blob[pos:pos+4])[0]
            if total == 0 or total > 65536 or pos + 4 + total > len(blob):
                break
            pay = blob[pos+4:pos+4+total]
            mm = ATT.match(pay)
            if not mm:
                break
            nm = mm.group(1).decode('ascii', 'replace')
            val = pay[len(mm.group(1)):]
            if nm.startswith('att-'):
                attrs = {'_att': nm, '_start': st}
                pos += 4 + total
                continue
            if nm.startswith('codes'):
                # 事件标记：紧跟的块名字就是代码
                nxt_total = struct.unpack('<I', blob[pos+4+total:pos+8+total])[0]
                code = blob[pos+8+total: pos+8+total+nxt_total].decode('gbk', 'replace')
                attrs[nm] = code
                pos += 8 + total + nxt_total
                continue
            kind, v = decode_val(val)
            attrs[nm] = v
            pos += 4 + total
        attrs['_end'] = pos
        out.append(attrs)
    return out

def find_type(path, want):
    blob = open(path, 'rb').read()
    for a in parse_blocks(blob):
        if a.get('type') == want:
            return blob, a
    return blob, None

if __name__ == '__main__':
    print("=== 工厂页面控件类型清点（修正解码后） ===")
    for f in sorted(glob.glob(r'.\extracted\*.pa')):
        blob = open(f, 'rb').read()
        bl = parse_blocks(blob)
        ts = []
        for a in bl:
            t = a.get('type')
            ts.append(chr(t) if isinstance(t, int) and 32 <= t < 127 else '?')
        print(f"  {os.path.basename(f):10s} 块={len(bl):>3} 类型={''.join(ts[:26])}")

    print("\n=== 找一个按钮('b') 和一个文本('t') 模板 ===")
    for want, label in ((ord('b'), 'BUTTON'), (ord('t'), 'TEXT'), (ord('p'), 'PICTURE')):
        found = None
        for f in sorted(glob.glob(r'.\extracted\*.pa')):
            blob, a = find_type(f, want)
            if a:
                found = (f, blob, a)
                break
        if found:
            f, blob, a = found
            seg = blob[a['_start']:a['_end']]
            print(f"\n--- {label}: {os.path.basename(f)}  块长={len(seg)}B  att={a.get('_att')}  objname={a.get('objname')!r}")
            print("    attrs:", {k: v for k, v in a.items() if not k.startswith('_') and not k.startswith('codes')})
            codes = {k: v for k, v in a.items() if k.startswith('codes')}
            if codes:
                print("    事件:", codes)
            print("    HEX:", seg[:64].hex(' '), '...')
            open(f'_tpl_{label.lower()}.bin', 'wb').write(seg)
        else:
            print(f"\n--- {label}: 没找到 ✗")
