# tjc-hmi-toolkit

**不用点那个上位机 GUI —— 直接解析、修改、生成整个 TJC / Nextion `.HMI` 工程文件。**

![license](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![python](https://img.shields.io/badge/python-3.9%2B-blue?style=flat-square)
![format](https://img.shields.io/badge/.HMI-reverse--engineered-purple?style=flat-square)
![tested](https://img.shields.io/badge/tested%20on-TJC8048X270__011R-orange?style=flat-square)

> **★这个格式官方没有公开文档** —— 本仓库的格式说明是从文件结构**反推**出来的（[docs/HMI格式说明.md](docs/HMI格式说明.md)）。
>
> **★最关键的一条：这个容器没有校验和** ⇒ 把任意字节改掉、重新打包，上位机照样能打开 ⇒
> **程序化生成整个工程是可行的**（本仓库所有工具的基础）

---

## 30 秒看懂

| | |
|---|---|
| **解决什么** | 要批量改几十个控件、写事件代码、删掉一页 —— 用编辑器手点**又慢又容易错，而且没法复现、没法自动化** |
| **怎么做到** | 解析 `.HMI` 容器 → 改数据块 → **重新打包**（容器无校验和 ⇒ 编辑器照样能打开） |
| **里面有什么** | 11 个脚本（5 个命令行 + 3 个库 + 3 个辅助）＋ 一份完整的**格式逆向说明** ＋ 一份诚实的"还没弄清的地方"清单 |

## 工具清单

| 工具 | 类型 | 干什么 |
|---|:---:|---|
| `hmi_container.py` | **命令行** | ★读容器：**自动探测目录起点** ＋ 报连续性（见下面「坑 1」） |
| `verify_hmi.py` | **命令行** | ★工程自检：容器连续率 / 页数 / 每页控件名逐条比对 / 事件代码可读性 |
| `hmi_gen.py` | **命令行** | 往指定页面**批量克隆控件**并改 `objname/x/y/w/h/txt`（按 JSON 规格） |
| `hmi_drop_page.py` | **命令行** | 从容器里**删掉一页** |
| `hmi_parse.py` | 命令行 | 容器 + 页面块的**诊断视图**（⚠️ 页面级属性解码不保证准，见「坑 2」） |
| `pa_dump.py` `pa_dump2.py` | 命令行 | 把页面块（`.pa` / `.page`）的 TLV 逐条打出来看 |
| `hmi_comp.py` | 库 | 控件块**编解码**（含「三条铁律」，见格式说明第 4.1 节） |
| `hmi_page.py` | 库 | 页面**组装**（头部 + 页面块 + 控件表） |
| `hmi_pack.py` | 库 | **重新打包**成 `.HMI`（保留原文件前段 = 魔数 + 目录 + 资源区） |
| `hmi_templates.py` | 辅助 | 导出「按钮/文本/页面」三种块的逐字节模板（要自己准备 `extracted/` 目录） |

---

## 快速上手

```bash
# ① 先看一个工程里有什么（最有用的一条命令）
python verify_hmi.py 你的工程.HMI
#   → 容器连续率 / 页面数量 / 每页控件名 / 事件代码

# ② 只想看容器目录（有哪些页、每项多大）
python hmi_container.py 你的工程.HMI

# ③ 看某一页的 TLV（先把页抽出来）
python -c "import hmi_container as C; r=C.read('你的工程.HMI'); e=[x for x in r['entries'] if x['name']=='0.pa'][0]; open('0.pa','wb').write(r['data'][e['off']:e['off']+e['len']])"
python pa_dump2.py 0.pa

# ④ 删掉第 5 页（先干跑看看它会做什么）
python hmi_drop_page.py 你的工程.HMI 少一页.HMI --page 5 --dry-run
python hmi_drop_page.py 你的工程.HMI 少一页.HMI --page 5

# ⑤ 批量克隆控件（按 JSON 规格）
python hmi_gen.py 你的工程.HMI 改好.HMI --page 0 --spec spec.json --dry-run
```

`spec.json` 大致长这样（字段含义以 `hmi_gen.py` 里的解析为准）：

```json
{
  "clone": {
    "from": "tTitle",
    "to": ["mWifi", "mIp", "mRom"],
    "x": 20, "y": 40, "dy": 36, "w": 200, "h": 30,
    "txt": ["WiFi", "IP", "ROM"]
  }
}
```

---

## 格式速览

```
.HMI  = [魔数 4B] + [目录 28B × N] + [数据区]
目录项 = [名字 16B(\0 填充)] [数据偏移 4B LE] [数据长度 4B LE] [标志 4B]
数据区 = main.HMI(页面索引) / N.pa(第 N 页) / Program.s(全局代码，明文) / 资源区(字库·图片，占大头)
页面   = [文件头] + [TLV…]，TLV = [4B 总长][属性名 + 值]，值写在载荷末尾、前面补 0
控件   = 每个控件一个 `att-N` 块；页面块是 `att-28`；★`total=0` 是分隔符不是文件结尾
事件   = `codesdown-N` 等是**无值标记块**，紧跟其后那个「名字就是代码」的块才是代码
```

完整版（含页面头结构、属性槽位长度、控件块三条铁律）→ **[docs/HMI格式说明.md](docs/HMI格式说明.md)**

---

## 坑（都是真踩过的）

### 1. 目录起点**不是固定值** ✗

实测到三种：`05 00 00 00`（新格式）→ 起点 **4**；`1a 02 00 00 00`（旧格式）→ **5**；
还有一种 `17 00 00 00` 的 → **4**，但**第一条目录项名字的首字节是 `0x00`** ✗

⇒ **写死任何一个起点都会静默读错**（不报错，只是**少一条**或整张错位）✗
⇒ 用 `hmi_container.py` 的**连续性判据**自动定起点 ✓（起点错位时连续率会掉到 0；正确时接近满分）

### 2. `hmi_parse.py` 的**页面级**属性解码不保证准 ⚠️

它的**容器解析已修**（改用 `hmi_container`），但页面块里属性值的定位方式和
`verify_hmi.py` / `hmi_comp.py` 不同 ⇒ **要看页面内容请用后两个** ✓，
`hmi_parse.py` 只当"快速扫一眼"的诊断视图。

### 3. 中文 Windows 控制台是 GBK

脚本里的 ✓/✗ 直接打印会 `UnicodeEncodeError: 'gbk' codec can't encode character` ✗
（`verify_hmi.py` 已加 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` ✓；
你自己写的脚本也建议加一句）

### 4. 还没弄清的地方（诚实清单）

目录项第 4 个字段（标志）的含义、页面文件头前 4 字节的哈希算法、资源区（字库/图片）的内部格式
—— 都**未解**（前两个不影响使用：哈希编辑器不校验，直接沿用原值 ✓）

---

## 适用范围

- ✅ 实测环境：**USART HMI 编辑器 1.68.1 ＋ TJC8048X270_011R（X2 系列，7" 800×480）**
- ⚠️ 别的编辑器版本 / 别的屏系列（X3 / X5 / K0 …）**没有验证过** —— 格式可能有差异，欢迎反馈

> **本仓库不含任何 `.HMI` 样本** ✗ —— 出厂工程和第三方工程都有版权，里面也可能有个人配置。
> 请拿你自己的工程试 ✓（工具不需要样本也能跑）

## 出处

这套工具是从 [**rom-watch**](https://github.com/cmyfqwq/rom-watch)（一块 ESP8266 做的"新版本监测看板"）里抽出来的
—— 那块串口屏本来是用来看板的状态显示器，为了让它显示中文界面才把格式啃了下来。

## 许可证

**MIT** —— 见 [LICENSE](LICENSE)。
