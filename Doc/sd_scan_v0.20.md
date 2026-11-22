# v0.20：SD 直接放 ROM（固件侧扫描）

## 目标

用户把 `.nes` / `.fds` 文件原样拷进 `F:\NES\`，插卡开机即可在菜单里看到并游玩。
不再需要 `LIBRARY.IDX`，不需要重命名，不需要在电脑上运行任何工具。

## 固件行为

1. **长文件名**：`ffconf.h` 打开 `FF_USE_LFN 1`（BSS 静态缓冲），`FF_MAX_LFN` / `FF_LFN_BUF` 为 64。
   FatFs 依赖的 `ff_uni2oem` / `ff_oem2uni` / `ff_wtoupper` 由 `User/fatfs/ffunicode.c` 提供，
   只实现 CP437；超出 CP437 的字符使 FatFs 回退到 8.3 短名，不会出现乱码路径。
2. **目录扫描**：`NesLibrary_Boot()` 用 `f_readdir` 遍历 `0:/NES`，只接受 `.NES` / `.FDS`
   （大小写不敏感），最多 64 项；跳过目录、隐藏和系统项。
3. **板端校验**（`nes_import.c`，与 `tools/embed_roms.py` 同规则）：
   读 16 字节头 + `f_size`，按 Mapper 检查 PRG/CHR 尺寸与 arena 上限，再 `f_lseek` 到复位向量。
   失败的文件不进入菜单，只计入 `N SKIPPED`。
4. **NES 2.0**：满足 `normalize()` 子集条件（NTSC、submapper 0、无 trainer/四屏/扩展设备）时，
   载入后在 RAM 内改写 16 字节头再交给 `Nes_Load`；卡上原文件不动。
5. **索引缓存**：首次扫描后写 `NES/INDEX.CCH`（`NESIDX2` + 目录快照哈希 + 每项名称/Mapper/大小）。
   下次开机只比对快照，命中就跳过逐个读头。缓存损坏或目录变化都会回退到完整扫描。
   缓存只用于加速，加载时仍重新校验头部，所以坏缓存不会放行坏 ROM。
6. **封面可选**：`NES/<同名>.COV` 存在就显示，缺失回退到原生图形。封面文件名由 ROM 文件名推导，
   不再依赖编号。
7. **旧卡兼容（只读）**：如果卡上仍是旧工具生成的 `G0000.NES` 这类编号名，固件会用
   `NES/LIBRARY.IDX` 里的标题作为**显示名**。索引只在显示阶段读取，不参与加载校验，
   也不会写卡；删掉索引对启动没有影响，只是标题会变成 `G0000`。

## 用户侧操作

- 把 ROM 直接放到 `F:\NES\`。
- 想要的菜单标题就是文件名（去扩展名、转大写）。例如 `Super Mario Bros. 3 (USA).nes`
  显示为 `SUPER MARIO BROS. 3 (USA)`。
- 旧卡上的 `LIBRARY.IDX` 只用于显示标题，不再参与加载；`INDEX.TSV`、`GAMES.JSON` 不再读取。
  若旧卡是 `G0000.NES` 这类编号名又想让标题跟随文件名，可改回可读名称（并同步改封面 `G0000.COV`）。
- `tools/prepare_sd.py` 保留为可选的打包器（生成已知良好的一包 + 封面），不再是使用前提。

## 边界

| 项目 | 限制 |
|---|---|
| 扫描目录 | 只扫 `0:/NES`，不递归子目录 |
| 单镜像 | 普通 640 KiB，MMC5 896 KiB（外扩 SRAM arena 上限） |
| 文件名 | 超过 63 字符的文件仍可打开，但菜单标题会退回 8.3 短名 |
| 非 CP437 名称 | 与上行相同，中文名会显示短名 |
| Mapper | 仍为 0/1/2/3/4/5/7/11/20/40/66/71；其余跳过并计数 |
| FDS | 只读；块结构在加载时校验 |
| 条目数 | 最多 64 |

## 开机耗时

冷启动（无缓存）需要逐个打开 ROM 读头与复位向量；缓存命中后只剩一次目录遍历。
本地 ARM 仿真：7 款游戏冷启动 141 个块读，缓存命中 20 个块读。
实机（2026-11-20，1 MHz SD）：冷启动 16 次文件读，复位后缓存路径 4 次文件读。

## 实机记录

2026-11-20 用 CMSIS-DAP 1 MHz 写入并全量读回（164,864 字节一致）。板上 SWD 只读确认：

- `sd_active=1`、`sd_count=7`，状态行为空、`nes_faults=0`、CFSR 为 0；
- 7 个标题正确（来自旧卡的 `LIBRARY.IDX` 显示回退）；
- 冷启动 16 次文件读，随后复位为 4 次，说明 `INDEX.CCH` 命中；
- 本轮没有进入游戏、没有注入按键、没有写存档。

报告：`Release/board_sdscan_v0.20.json`。备份：`backups/flash_20261120_231431.bin`。

## 验证

- `Tests/test_sd_library_arm.py`：真实 ARM FatFs 扫描真实 FAT32 镜像，含 LFN 名称、封面、
  arena 边界、64/65 条上限、非法 Mapper/坏头/截断文件计数、缓存命中、目录变更失效、
  缓存损坏回退、无卡/坏 FAT 回退。
- `Tests/render_menu_arm.py --sd`：菜单按扫描结果显示 7 款完整名称，封面逐像素一致。
- `Tests/test_sd_saves_arm.py`、`test_discrete_mappers_sd_arm.py`、`test_rpg_controls_arm.py`
  在扫描路径下回归通过。

以上均为本地仿真结果，不是板上照片或实机帧率。
