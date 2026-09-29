# hmi_pack.py —— 打包：保留原文件"魔数+目录+资源区"前段，只重写数据段并更新目录项（数据区保持连续 ✓ 不加填充）
import struct

def repack(path, magic, ents, blobs, original, verbose=True):
    first_off = min(e['off'] for e in ents)
    head = bytearray(original[:first_off])        # 魔数 + 目录 + 资源区 全部保留 ✓
    off = 4
    cur = first_off
    body = bytearray()
    for e, b in zip(ents, blobs):
        head[off:off+16] = bytes(e['name'])[:16].ljust(16, b'\x00')
        struct.pack_into('<III', head, off+16, cur, len(b), e['flag'])
        body += b
        cur += len(b)
        off += 28
    out = bytes(head) + bytes(body)
    open(path, 'wb').write(out)
    if verbose:
        print(f"  packed {path}  {len(out):,}B  (resources kept {first_off:,}B, data {len(body):,}B)")
    return path
