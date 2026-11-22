# SD 游戏库使用与验收记录（v0.17，2026-11-18）

更新：v0.17.5 已增加 SD 电池存档、FDS 换面及扩展音源，详见 [saves_fds_v0.17.5.md](saves_fds_v0.17.5.md)。下文的只读、第一面及无持久存档描述属于 v0.17 历史状态。

## 已实现

- 板载 SDIO 轮询读卡、只读 FatFs R0.16，FAT32、8.3 短文件名；PC8～PC11 数据、PC12 时钟、PD2 命令，摄像头保持断开。沿用本地同款板驱动，保留第三方版权说明。
- 启动读取 `/NES/LIBRARY.IDX`，最多 64 款，屏幕标题仍为完整英文名（最多 46 字符），不受 SD 文件短名限制。
- 菜单读取 NCV1 封面，支持 4/8 位索引与竖版海报，尺寸、长度与 payload CRC32 校验；连续访问同一封面有缓存。
- 开始游戏时，按索引核对大小和 ROM CRC32，一次性预载到外扩 SRAM，然后调用既有 Nes_Load。游戏循环不读卡，SD 卡容量不等于内存容量或 Mapper 覆盖范围。
- 无卡、坏 FAT 或坏索引退回当前内置 SMB1 并显示原因；单个 ROM 缺失、短读、校验错或不支持的头部在菜单提示。封面错误使用默认图形，不影响其余游戏。
- 菜单/加载期间音频 DMA 输出零，不执行 APU，也不访问正在被覆盖的 ROM；进入游戏后恢复，避免仅软静音仍后台取样的问题。
- FDS BIOS 仍是此前验证的内置 8 KiB；卡上的 DISKSYS.ROM 保留作资源包备份，当前不热加载它。仍为 FDS 只读/第一面，无扩展音频或持久存档。

## 固件与空间

默认：`Release/NesFire_v0.17-sd-preview.hex` / `.bin`，BIN 137216 字节（134 KiB），Code=79092、RO-data=56124、RW-data=264、ZI-data=78088。全量构建 0 errors / 0 warnings。其余 ROM 与封面不再编入 Flash；第一款游戏（当前 SMB1）作为兜底保留。

可选 `build.ps1 -Embedded` 仍能生成全内置版本，须满足总镜像 768 KiB 及链接器 Flash 容量。默认 SD 库最多 64 项、单个镜像最多 640 KiB；合法 Mapper/容量/NTSC 限制仍由导入器和内核共同检查。

当前没有烧录、连接 DAP/SWD、复位开发板或实机采样。Flash 下降不代表运行性能已验收：SDIO 读卡稳定性、外扩 SRAM 取指成本、FDS 时序和耳机播放需之后实机测量。

## 卡上文件与新增游戏

本次已确认 F: 为用户 FAT32 16 GB 卡。已有五款游戏、COV 和 BIOS 共 11 项内容与本机包一致；新增 `LIBRARY.IDX` 和 `SD17.JSON` 两个文件。没有覆盖、删除或格式化，原 `TH06` 保留。历史 `INDEX.TSV` / `GAMES.JSON` 未改，固件不读取它们。

从 `D:\Project\BA_Game` 执行：

```powershell
# 导入与本地构建；自动准备 Release/SD_ROOT/NES，不会写读卡器或烧录。
.\Nes_fire_emulator\add_game.ps1 -Rom 'D:\Games\new_game.nes' -Name 'FULL GAME NAME' -Build

# 不编译、只重建本机卡目录也可以：
python .\Nes_fire_emulator\tools\prepare_sd.py

# 确认当前盘符后安装。显式允许更新两个生成的索引/说明文件；
# 不覆盖内容不同的已有 ROM/封面，不接触 NES 以外的目录。
python .\Nes_fire_emulator\tools\install_sd.py F:/ --update-index
```

如果只想新增缺失文件、不允许更新任何已有文件，省略 `--update-index`。不同内容的现有 ROM/封面即使加此参数也会拒绝，须用户先备份并决定如何更换。不要把安装命令中的 F: 视为永久盘符。

卡根目录的 `NES` 内，`G0000.NES` / `.FDS` 为镜像，`G0000.COV` 为封面。`LIBRARY.IDX` 第一行 `NESLIB1`，后续每行六个 TAB 分隔字段：短文件名、完整标题、可空封面名、十进制镜像长度、八位十六进制 CRC32、十进制 Mapper。文件以 LF 换行并保留末尾换行，由工具生成，固件拒绝重复名、路径穿越、超长标题、无效数字、超限库或不支持的 Mapper。

NCV1 保留原封面像素。Python 工具也提供解码及 CRC/长度检查；未使用板载 PNG/JPG 解码器，不为菜单分配整屏帧缓冲。

## 外扩 SRAM 分区

| 地址范围 | 用途 |
|---|---|
| `0x6C000000～0x6C020000` | 原始 CHR |
| `0x6C020000～0x6C040000` | 解码图块 |
| `0x6C040000～0x6C05E000` | 原有 RGB565 截图缓存 |
| `0x6C060000～0x6C100000` | 卡带 ROM / 菜单封面共享 640 KiB，互斥使用 |
| `0x6C0E0000～0x6C100000` | 仅 FDS 活动时的合成磁盘字节流 |

FDS 原始镜像最多八面加头，尺寸小于 512 KiB，因此从 `0x6C060000` 载入后结束于 `0x6C0E0000` 之前，不会覆盖合成流。卡带可复用顶部区域，切换时先卸载 FDS。只有停止游戏、音频暂停处理后才允许封面复用 arena；运行中请求封面会被拒绝。

## 本地验证

实际执行 Keil AXF 中的 FatFs、库解析、COV 校验、ROM 加载、6502/PPU/APU 和菜单代码；仅替换 SD 硬件扇区、GPIO/LCD 端口。测试盘为独立内存 FAT32，不冒充物理卡测试。

- `test_sd_library_arm.py`：五款读回与 COV 逐像素核对、缓存、运行期不读卡、arena 边界、无卡/坏 FAT/缺文件/短读/CRC/坏头拒绝、64 项接受与 65 项拒绝、4 位奇数像素与 8 位/竖版封面。
- `test_sd_gameplay_arm.py`：从实际 ARM FatFs 加载的 SMB3 标题/地图/1-1/移动/B+A/PCM；Metroid 与 Wizards 开始/移动/跳跃/PCM；SMB2 BIOS 启动及进入 1-1。报告 `Tests/nes_output/sd_gameplay_results.json`。
- `render_menu_arm.py --sd`：从 SD 读封面，五项滚动、完整名称、防误选、Settings 进入/返回、LCD 边界、原图逐像素核对。
- `test_sd_audio_mute_arm.py`：实际 DMA 半传输中断路径在静音时不调用 APU，输出零；解除后恢复。
- `test_sd_install.py`：临时目录验证新装、重复安装、用户文件保留、冲突预检、显式元数据更新。
- 既有 Mapper、音频、60 Hz 逻辑/20 Hz 显示调度、导入回滚与封面格式测试继续通过；保留 Embedded 构建供全内置回归。

所有本地测试不能替代 SDIO 物理总线、LCD 实拍、耳机实听或帧率验收。发布汇总在 `Release/sd_v0.17_report.json`，卡上复制记录在 `Release/sd_install_v0.17.json`。
