# pa_dump2.py —— 从第一个 'att-' 标记起解 TLV（前面那段是文件头）
import sys, struct, re, os

def find_tlv_start(blob):
    i = blob.find(b'att-')
    if i < 0:
        return None
    return max(0, i - 4)

def dump(blob, title, maxn=120):
    print(f"\n=== {title}  {len(blob)} bytes ===")
    hdr = blob[:find_tlv_start(blob) or 0]
    asc = ''.join(chr(c) if 32 <= c < 127 else '.' for c in hdr[:64])
    print(f"  header({len(hdr)}): {asc}")
    pos = find_tlv_start(blob)
    if pos is None:
        print("  没有 att- 标记 ✗")
        return
    n = 0
    while pos + 4 <= len(blob) and n < maxn:
        total = struct.unpack('<I', blob[pos:pos+4])[0]
        if total <= 0 or total > 8192 or pos + 4 + total > len(blob):
            print(f"  [{pos}] 停：total={total}")
            break
        payload = blob[pos+4:pos+4+total]
        m = re.match(rb'([\x20-\x7e]{1,24})', payload)
        if not m:
            pos += 4 + total; n += 1; continue
        name = m.group(1).decode('ascii')
        val = payload[len(name):]
        iv = int.from_bytes(val[-4:], 'little') if len(val) >= 4 else None
        sv = val.decode('gbk', 'replace') if val else ''
        pr = ''.join(ch if (32 <= ord(ch) < 127 or ord(ch) > 127) else '.' for ch in sv)[:34]
        extra = f"int={iv}" if (iv is not None and iv < 1 << 24) else ''
        if pr.strip('.'):
            extra += f" str='{pr}'"
        print(f"  [{pos:>5}] {name:16s} len={total:<5} {extra}")
        pos += 4 + total; n += 1

if __name__ == '__main__':
    for p in sys.argv[1:]:
        try:
            dump(open(p, 'rb').read(), os.path.basename(p))
        except Exception as ex:
            print(f"  FAIL {p}: {ex}")
