# pa_dump.py —— 解析 TJC 页面块（.pa/.page）的 TLV： [4字节总长 N][属性名][值]，N = 名字长度 + 值长度
# 值的实际数据以小端写在末尾（前面补 0）
import sys, struct, re

def dump_pa(blob, title=''):
    print(f"\n=== {title}  {len(blob)} bytes ===")
    print("  前 96 字节 hex:", blob[:96].hex(' '))
    pos = 0
    n_attr = 0
    while pos + 4 <= len(blob):
        total = struct.unpack('<I', blob[pos:pos+4])[0]
        if total == 0 or pos + 4 + total > len(blob) + 8 or total > 4096:
            print(f"  [pos {pos}] 长度异常 total={total} -> 停")
            break
        payload = blob[pos+4:pos+4+total]
        # 属性名 = 开头的可打印 ASCII；剩下的是值
        m = re.match(rb'([\x20-\x7e]{1,24})', payload)
        if not m:
            print(f"  [pos {pos}] total={total} 无属性名: {payload[:24].hex(' ')}")
            pos += 4 + total
            continue
        name = m.group(1).decode('ascii')
        val = payload[len(name):]
        # 值：小端数值在末尾
        iv = int.from_bytes(val[-4:], 'little') if len(val) >= 4 else None
        sv = ''
        try:
            sv = val.decode('gbk', 'replace')
        except Exception:
            pass
        show = f"val[{len(val)}]"
        if iv is not None and iv < 1 << 24:
            show += f"  int={iv}"
        printable = ''.join(ch if 32 <= ord(ch) < 127 or ord(ch) > 127 else '.' for ch in sv)[:40]
        if printable.strip('.'):
            show += f"  str='{printable}'"
        print(f"  [{pos:>5}] {name:16s} total={total:<5} {show}")
        pos += 4 + total
        n_attr += 1
        if n_attr > 200:
            print("  ...(截断)")
            break
    print(f"  共解出 {n_attr} 个属性块")
    return n_attr

if __name__ == '__main__':
    for p in sys.argv[1:]:
        try:
            data = open(p, 'rb').read()
            dump_pa(data, p.split('\\')[-1])
        except Exception as ex:
            print(f"  FAIL {p}: {ex}")
