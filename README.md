# NES Fire Emulator

## v0.71 正式交付基线

- 横屏游戏保持 640×480 居中 4:3，左右各 80 px 侧边面板：深色渐变、当前封面缩略图和文件名前 5 个字符；CAP 切换横竖屏时重绘。
- SDIO 提升到 8 MHz，`BSP_SD_ReadBlocks` 改为一次多块读取；20 KB 封面从 40 次单块调用降到 1 次。
- 设置中心所有页面支持 CAP 一键横竖屏（CONTROL 页保留电容键原始测试）；SCREEN/AUDIO 切换后立即重设 LCD 扫描并重绘。
- 屏蔽面板 A 键从 PC6 迁到 PE3，PC6 固定为 WM8978 I2S2_MCK；修复按键初始化把 MCLK 改成输入导致耳机和扬声器同时无声的问题。
- 新增 `tools/dedup_sd.py` 保守去重（按英文标题保留一个，ROM+COV 成对隔离，重映射 PREFS、重置 CATALOG）和 `tools/sort_catalog.py` 英文标题排序。
- 固件 `NesFire_v0.71-settings`，198,656 字节全片回读通过。
- 正式交付：`LICENSE` 为 MIT；ROM、FDS BIOS、封面和字模不随仓库分发，见 `.gitignore`。

## v0.43 通用画面提速

所有卡带和 FDS 共用同一条显示路径。固件在 STM32F407 的 CCM 中保存上一幅 256×240 的调色板索引，逐行比较，只将有变化的区段放大后送往 LCD。游戏画面保持 480×450。调色板切换、进入游戏和从存档错误页恢复时会重绘。PPU 用查表计算背景像素颜色和精灵优先级所需的遮挡标记，支持细滚动和 MMC5 分屏。

调度器以 60 逻辑帧/秒为目标，根据近期绘制帧和跳绘帧的实测耗时调整绘制间隔。每个逻辑帧仍执行游戏和输入。实机对照脚本使用四款游戏的关卡输入序列，并记录逻辑帧率、绘制帧率以及向 LCD 发送了变化像素的帧数。 [板测脚本](tools/benchmark_frames_board.py)

同一块板、同一张卡，以每款约 240 个逻辑帧的关卡窗口测得下列 LCD 更新率。旧版每次绘制都送屏，新版计入实际向屏幕写入像素的帧。单位为帧/秒，采用板载毫秒计数，单个窗口约四至五秒。 [v0.42 原始数据](Release/validation/0.42-arm67-validation/board-fps-four-games.json) · [v0.43 原始数据](Release/validation/0.43-render/board-fps-four-games.json)

| 游戏 | Mapper | v0.42 | v0.43 |
|---|---:|---:|---:|
| Super Mario Bros. | 0 | 16.6 | 26.1 |
| Metroid | 1 | 16.9 | 22.4 |
| Super Mario Bros. 3 | 4 | 16.7 | 24.2 |
| Wizards & Warriors | 7 | 16.7 | 21.6 |

在 v0.43 上用主机单调时钟与板上 DWT 周期计数独立复测，四款游戏约 60 逻辑帧/秒。保持游戏输入和外设配置一致，分别启用和推迟每秒 USART1 日志，约四秒的窗口内 LCD 更新率变化为 −0.13 至 +0.28 帧/秒。保留日志时，四款按上表顺序分别测得 26.0、21.6、24.0、20.3 次实际 LCD 更新/秒。《巫师与战士》固定场景中，板载毫秒计数会高估帧率，使用主机或 DWT 计时复核。 [串口对照记录](Release/validation/0.43-render/board-fps-uart-ab.json)

## v0.42 候选版

- 游戏库按完整标题、文件名和已有拼音别名搜索。清空搜索或没有匹配会回到当前视图。旧 `SEARCH.IDX` 可以留在卡上，固件搜索直接读取完整目录。
- 短按 KEY1 打开设置中心，不再需要长按。第一层为 ALL GAMES / LOADABLE / UNSUPPORTED / FAVORITES / RECENTLY PLAYED / SEARCH / CONTROL / AUDIO / SCREEN / FAVORITE；A 进入子页，B/KEY1 返回上一层。SEARCH 同时保留 KEY2 快捷入口。音量、音源、默认横竖屏和收藏改动立即写入卡上 `NES/SETTINGS.BIN`，掉电重启后自动恢复；卡写失败只丢持久化，不影响当前运行。
- 兼容提示显示 Mapper 和预检原因。首次选择兼容性筛选会分批检查，KEY1 可取消。可用 [prepare_library.py](tools/prepare_library.py) 在电脑上生成兼容性报告、当前目录专用的 `COMPAT.IDX` 和带拼音的目录副本。预检通过的游戏仍需验收画面、声音、后续关卡和存档。
- 长按摇杆 SW 时自动保存电池存档。成功后回到游戏库并显示结果。写卡失败时保留当前运行状态，KEY2 / SW 重试，KEY1 返回游戏。
- 目录上限 2,048 项，超限会提示遗漏数。允许文件名中出现连续点，拒绝 `.` 和 `..` 路径段。已有中文标题、拼音和同名封面继续使用。
- 离线 ARM 渲染已覆盖设置中心首页、CONTROL/AUDIO/SCREEN 子页及 800×480 横屏；`Tests/test_settings_arm.py` 校验 `SETTINGS.BIN` 的记录/CRC/掉电回退和音量增益。预览为 `Tests/nes_output/settings_*.png`，仍是本地仿真输出，不是板上照片。
- 2026-11-23 已通过 CMSIS-DAP 烧录 `NesFire_v0.63-settings.hex` 并完成 195,584 字节全片回读；SWD 实测设置首页、AUDIO 子页、SCREEN 切换写卡和逐层返回。此前板子仍运行 v0.41，上一轮只构建未下载；记录见 `Release/dap_download_v0.63-settings.json` 与 [设置中心文档](Doc/settings_centre.md)。
- 中文字模改用 24 px 黑体重新生成，修复宋体细横/撇捺二值化后的断笔；新 `FONT.MAP`/`FONT.HZK` 在 `Assets/fonts/cjk`，旧宋体备份在 `backups/font_simsun24_20261123`。字模在 SD 卡上，已通过 SWD 写入实卡并逐块回读校验，旧文件保留为 `.OLD`；原因与验证见 [中文字模说明](Doc/cjk_font.md)。
- 游戏库列表只显示拉丁标题（Flash 16 px 字体），不再逐行读中文字模；按 SELECT（扩展板 E）打开 GAME INFO，显示完整中文名、序号、大小、Mapper、头信息、收藏和 FDS。A 启动、B 返回。CAP 电容键保持原先的一键横竖屏切换；游戏内 CAP/SELECT 仍是 NES Select。详见 [列表与详情页](Doc/library_details.md)。
- 卡上 `NES/famicom/` 有 1550 个 ROM + 1550 个 `.COV`（3100 项），FatFs 按路径线性扫描，实测封面约 1.25 秒、末尾 ROM 约 2.5 秒；前 7 个在 28 项根目录约 1 毫秒。`tools/bucket_sd.py` 可按 100 个一组分桶，并重映射收藏/最近记录、重置目录缓存；详见 [SD 分桶与封面来源](Doc/sd_bucketing.md)。
- `NesFire_v0.65-details` 已通过 CMSIS-DAP 烧录并完成 196,608 字节全片回读；修复了 GAME INFO 按 B 返回后同一个仍按住的 B 又打开设置的问题（返回列表时清 `menu_armed`）。SWD 实测 `opened=7 → after_b=0`，继续按住仍为 0，松开后才重新武装。
- `NesFire_v0.67-title` 已通过 CMSIS-DAP 烧录并完成 197,632 字节全片回读：CAP 恢复菜单横竖屏一键切换，SELECT（E）保留 GAME INFO；目录标签在 96 字节处截断时（例如第 158 项 `...(JAPAN`）列表和详情自动回退到完整文件名，补回缺失的右括号。
- 构建版本见 [Release/VERSION](Release/VERSION)。上板检查、只读计数器和验收顺序见 [板测流程](Doc/board_validation.md)。此前经烧录和完整回读验证的发布记录见 [v0.41](Release/dap_download_v0.41-align.json)。

## v0.22 历史记录

v0.22 把 SD 游戏库扩到几百个 ROM，并支持中文文件名：固件递归扫描 `NES/`（三层子目录），
目录表 `NES/CATALOG.IDX` 存在卡上（272 字节定长记录、1024 项上限），RAM 只保留 4 条窗口；
FatFs 改用 UTF-8 长文件名，菜单按 16 px 一格渲染中英混排，中文字模来自卡上的
`FONT.MAP` / `FONT.HZK`（16×16，7445 字）。可选 `TITLES.DB` 用
`crc32(大小‖前4KiB‖后4KiB)` 指纹映射正式名；文件名本身可读时不必放它。
菜单条目计数改为 16 位，左右方向按 5 条翻页；以 `.` / `_` 开头的目录和 `SAVES` 不扫描，
方便放归档。

2026-11-20 已烧录 v0.22（168,960 字节读回一致）；无卡启动回退正常、faults/CFSR 为 0。
插卡后的首次开机需要重建目录表，406 个 ROM 预计多花 1–3 秒；之后复用缓存。
设计、卡上布局与验证见 [卡上游戏库](Doc/sd_library_v0.22.md)。

下面是此前 v0.20 的记录。

v0.20 把 SD 游戏库改为**固件自己扫描目录**：用户把 `.nes` / `.fds` 原文件直接放进 `F:\NES\`，
开机即可在菜单看到并游玩，不再需要 `LIBRARY.IDX`、重命名或任何电脑侧处理。
本版打开 FatFs 长文件名（`FF_USE_LFN 1`，CP437 转换由新增的 `User/fatfs/ffunicode.c` 提供），
新增 `User/nes/nes_import.c` 在板端按与 `tools/embed_roms.py` 相同的规则校验头部、尺寸、
复位向量与 arena 上限；不支持的 ROM 只计入 `N SKIPPED`，不进入菜单。
NES 2.0 普通 NTSC 头在载入后于 RAM 内归一化，卡上文件不被修改。
首次扫描后固件写 `NES/INDEX.CCH`（目录快照哈希 + 每项名称/Mapper/大小），之后开机命中缓存
只做一次目录遍历；缓存损坏或目录变化自动回退完整扫描，加载时仍重新校验。
旧卡（`G0000.NES` + `LIBRARY.IDX`）仍能显示正确标题：索引只用于显示名，不参与加载。

2026-11-20 已通过 CMSIS-DAP 写入并全量读回校验（164,864 字节，SHA-256
`a45da1fd…96c849`）；SWD 只读确认板上 `sd_count=7`、标题正确、faults 与 CFSR 为 0，
冷启动 16 次文件读、复位后缓存路径 4 次。记录见 `Release/board_sdscan_v0.20.json`，
设计、边界与验证见 [SD 直接放 ROM](Doc/sd_scan_v0.20.md)。
本轮未验证游戏流程、帧率、实机长文件名与存档写入。

下面是此前 v0.19.1 的验收记录。

v0.19.1 为当前 Just Breed 日版镜像增加四方向主轴/滞回和 A/B/Start 优先处理，松键后无需重新回中；原有按键定义和其他游戏输入路径保留。只读实机基线观察到 v0.19 约 39 逻辑帧/秒，因此同时将 MMC5 解码 cache 扩为 64 KiB，并对该 RPG 按绘制耗时调节画面提交频率。同场景 ARM 内核指令数减少 23.91%，画面和 CPU/RAM/SRAM 状态一致；这不是实机帧率结果。专项和既有回归通过，全量编译零错误/零警告；本版未烧录、未写物理 SD 卡，效果待用户实测。步骤、适配范围与限制见 [Just Breed 操作调整](Doc/justbreed_controls_v0.19.1.md)。下面是此前 v0.19 的验收记录。

实机验收更新（2026-11-19）：用户自行烧录 v0.19 后，确认恶魔城 III（USA）的画面、方向/跳跃/攻击和声音正常；Just Breed（Japan）的开场文字、城镇画面和音乐正常。运行中只读 Flash 全量比对一致，菜单识别七款游戏、扬声器路由及错误计数正常。本轮没有下载、复位或注入按键。验收只覆盖上述基本流程；游戏实测帧率、后续章节、长期运行及板上存档冷恢复未验证。记录见 `Release/user_acceptance_v0.19.json`；下文未上板等表述保留为开发阶段记录。

v0.19 新增基础 MMC5（Mapper 5），接入 PRG/CHR 换页、独立背景/精灵取图、ExRAM 扩展属性、填充名称表、扫描线 IRQ、乘法器、8 KiB RAM 保护、两路脉冲及直接 PCM。实际 ARM/FatFs 已验证用户的美版恶魔城 III 标题至 1-01、移动跳跃；Just Breed 的姓名输入、城镇剧情、扩展音频及 8 KiB 存档保存/冷恢复。Just Breed 尚未验收自由移动、战斗和后续流程。ROM 按需解码 cache 使 MMC5 单镜像上限为 896 KiB，其他 Mapper 仍为 640 KiB。七款游戏、封面和索引已回读校验安装到 F:，未烧录或复位开发板，默认扬声器保留。PCM 读监听/IRQ、大 WRAM 及点级时序尚未实现，详细范围和手动使用步骤见 [MMC5 v0.19](Doc/mmc5_v0.19.md)。新卡索引需配套 v0.19 固件；下面保留历史记录。

v0.18 离线新增 Mapper 11（Color Dreams）、66（标准 GxROM）和 71（Camerica / Fire Hawk 旧 iNES 兼容模式），同时接通导入器、SD 索引与加载校验。新增换页、实际 6502 跨页执行、CHR 原始数据/解码缓存、镜像别名、66 总线冲突与 RMW 两次写入、输入头部拒绝和无 PRG RAM 控制的自制 ROM 测试。三类均已通过实际 Keil ARM 代码及内存 FAT32 加载验证；尚无对应商业游戏或实机验收。本轮不烧录、不复位开发板、不写物理 SD 卡，默认音频仍为扬声器。容量、板型与验收边界见 [当前 Mapper 范围](Doc/mapper_support.md) 和 [v0.18 说明](Doc/mappers_v0.18.md)。下面各版本记录按历史状态保留。

v0.17.7 按用户要求将开机及复位后的默认输出改为 SPEAKER：WM8978 初始化即启用 SPK+/SPK− 桥接反相输出、关闭并静音耳机输出，扬声器音量保留 36；Settings 默认显示扬声器，仍可左右切换耳机／扬声器／静音。菜单和 SD 加载静音继续保留。全量构建零错误／零警告，实际 ARM 冷启动/重新初始化寄存器、输出切换和 DMA 静音测试通过。用户自行上板后，149504 字节运行中只读 Flash 比对一致，扬声器配置、DMA 及音频计数正常，Codec/DMA/APU/CPU 错误为 0；用户确认音乐和音效正常，手动复位后仍为默认扬声器。只读采样期间的重启已由用户确认是手动操作，本轮没有下载、复位、注入按键或请求写卡。验收范围仅为扬声器功能，见 Release/board_speaker_acceptance_v0.17.7.json。固件为 Release/NesFire_v0.17.7-speaker-preview.hex。

v0.17.6 仅离线优化：FDS 包络使用 32 位硬件除法快路径并保留长间隔溢出回退；双包络及调制的 256 采样基准从 752052 降至 71901 条 ARM 指令（约减少 90.44%），该基准输出逐字节一致，不代表整机性能比例。修复奇数位置调制表写入；加入 24 个扇区预算的存档中断恢复场景，增加 SAVING... 及存档错误优先显示。构建和 ARM 回归通过，详情见 [Doc/offline_optimization_v0.17.6.md](Doc/offline_optimization_v0.17.6.md)。本版未烧录；前一版 v0.17.5 已完成 Flash 校验，尚未进行存档/换面/音源的实体功能验收。

v0.17.5 增加三项功能：SD 游戏库中带 battery 标志卡带的 8 KiB 电池 RAM 在返回菜单时双槽校验保存、再次启动自动恢复；多面 FDS 用 Select＋摇杆左／右换面，模拟取盘／插盘且不重启游戏；FDS 波表、包络和调制音源混入原有 APU。存档不是即时状态，也未实现 FDS 写盘。原有音频输出选择和 NMI 画面修正保留。实际 ARM＋模拟 FAT32／HAL 的专项及五款游戏回归通过，完整说明见 [Doc/saves_fds_v0.17.5.md](Doc/saves_fds_v0.17.5.md)。用户随后授权通过仿真器烧录，149504 字节完整读回一致；后续改为离线工作，未进行实体卡写入、多面游戏或音源听感验收。原 SD 卡游戏文件不必重拷。

v0.17.4 增加 Settings 的 HEADPHONES / SPEAKER / MUTE 输出选择：游戏库按 KEY1 进入，摇杆左右每次拨动切换一项，长按 SW 1.5 秒返回。选择对所有游戏生效，本次上电期间保留，复位后恢复耳机。扬声器采用 WM8978 的 SPK+/SPK− 桥接反相输出，初始音量较低；切换先静音再配置，未选择的输出关闭。静音游戏仍排空 APU，菜单/加载继续隔离 APU。全量构建及路由、I2C 故障、DMA、Settings、SD 库回归通过，本版未上板，由用户烧录 Release/NesFire_v0.17.4-audio-preview.hex 后确认听感。操作及验证见 Doc/audio_output_v0.17.4.md。

v0.17.3 修正 CPU 在整段执行结束才处理 NMI 的延迟，改为入口优先处理待决 NMI，并计入 7 周期中断开销，消除 Wizards & Warriors 的上下跳动/状态栏闪烁。用户已于 2026-11-18 自行烧录并确认“解决了”；本地连续绘制/跳帧画面与 CPU 状态、五款 SD 路径和音频回归通过。以下为此前 SD 修复记录。

v0.17.2 已于 2026-11-18 经用户授权烧录，138240 字节完整 Flash 读回一致。除 v0.17.1 的内部 SRAM 单扇区中转及降速读取外，修正固定 3.3V 主机的初始化协商：不再请求 1.8V 切换，使用卡支持的电压窗口，并限制未就绪轮询时间。实机首次初始化成功、读出五项索引、五张封面循环及 SMB3 从 SD 预载通过；SMB3 的 SRAM 内容与原始 ROM 完全一致，逻辑 61 Hz、绘制 20 Hz，读卡重试、CPU 异常、音频 DMA 错误和 APU 队列丢弃均为 0，运行中不再读 SD。SMB2 FDS 从卡预载逐字节一致，进入 1-1、右移及 B+A 加速跳通过，逻辑约 60 Hz、画面约 20 Hz。报告为 Release/board_sd_v0.17.2-sd-preview.json 和 Release/board_sd_fds_v0.17.2-sd-preview.json。其余三款的游戏流程属于本地 ARM 回归，未在本次板测逐款游玩。

v0.17.1 针对用户插卡后报错：v0.17 只读现场显示 SD 与五项索引已初始化，但 HAL 记录 RX FIFO overrun (`0x20`)。修复版改为 1 MHz/4 位轮询、内部对齐单扇区中转、错误恢复及重试；初始化失败可回退 400 kHz/1 位，并区分初始化/总线/读取/格式错误提示。构建及 ARM 包装驱动/文件系统/菜单回归通过，详情见 Doc/SD_read_fix_v0.17.1.md。修复版是否已上板以独立下载和板测报告为准，历史 v0.17 现场数据不是本版验收。

v0.17 已接入只读 SDIO / FatFs 游戏库：开机读取 `NES/LIBRARY.IDX`，菜单从卡上读 COV 封面，选中后将完整 ROM 预载到外扩 SRAM，游戏运行期不访问卡。默认 SD 构建只保留第一款游戏（当前 SMB1）作为无卡兜底，不再把其余 ROM/封面编入 Flash；BIN 为 137216 字节（134 KiB），构建零错误/零警告。`build.ps1 -Embedded` 可生成全内置回归版本。FDS BIOS 继续使用已验证的内置 8 KiB 镜像。

真实 ARM FatFs + 模拟 FAT32 块设备的五款 ROM/封面校验、异常目录/短读/CRC/内存边界测试，以及 SD 路径上的 SMB3、Metroid、Wizards 和 SMB2 进入 1-1、输入/PCM 回归通过。菜单防误选、原生 Settings、封面逐像素核对和音频 DMA 静音隔离也通过。本段属于本地仿真结果；本次 SD 实机验证见首段，LCD 外观与耳机实际听感仍需用户确认。

F: 卡已补充 `NES/LIBRARY.IDX` 与 `NES/SD17.JSON`，新增 2 个文件，ROM/封面/BIOS 均读回 SHA-256 一致；没有格式化、没有覆盖旧文件，TH06 保留。旧 INDEX.TSV/GAMES.JSON 是历史打包说明，固件使用新索引。操作说明见 [Doc/SD_card_v0.17.md](Doc/SD_card_v0.17.md)，记录为 Release/sd_install_v0.17.json。以下为历史版本记录。

v0.16 已从用户提供的两个 ZIP 中仅读取 .nes 文件，保留原始字节，加入 METROID（Mapper 1）及 WIZARDS & WARRIORS（Mapper 7）。两款游戏的真实 Keil ARM 仿真验证覆盖标题、Start 进入场景、右移、初始位置跳跃及 PCM；CPU 错误和 APU 队列丢弃为 0。跳跃以 OAM 实际几何位置核对，不把地图/过场当作进入游戏。Metroid 1162 帧，Wizards 1402 帧；后续关卡、长期游戏和实机性能尚未验收。

五款游戏现已合装，菜单可滚动，原生 Settings 和单次拨动选择保留。五款标题封面均保持 256×240 原图，以 4 位索引无损存储；多于 16 色的自定义图片仍走 8 位路径。封面总计 153760 字节；构建 Code=67720、RO-data=931472、RW-data=248，约剩 48 KiB Flash，0 errors / 0 warnings。新固件 Release/NesFire_v0.16-games-preview.hex 未烧录。新游戏报告为 Tests/nes_output/mmc1_axrom_games_results.json。

用户另有 16 GB SD 卡。已核对本地板卡 SDIO/FatFs 例程，并准备五款游戏、原生封面、BIOS 与索引。2026-11-18 已确认电脑读卡器盘符 F:、文件系统 FAT32，将 13 个文件（927056 字节）复制到 F:\NES，逐文件 SHA-256 读回一致；原有 TH06 目录保留，没有格式化或覆盖。**当前 v0.16 固件仍从内部 Flash 加载游戏，尚未接入 SD 文件读取。** 记录在 Release/sd_copy_v0.16.json，SD 目录与后续迁移约束见 Doc/SD_card_plan.md。以下为历史版本说明。

v0.15 本地扩展 Mapper 1（基础 MMC1B）及 Mapper 7（AxROM）。MMC1 实现五位串行写入/复位、16/32 KiB PRG 模式、4/8 KiB CHR、单屏/水平/垂直镜像、8 KiB PRG RAM 控制及合法绝对寻址 RMW 的连续写处理；AxROM 实现 32 KiB PRG 换页、单屏镜像和 CHR RAM。导入器同步支持两类，保留三款 Mario、原生 Settings、单次拨动选择和清晰封面。构建零错误/零警告，新增 8 组真实 ARM 自制 ROM 测试与现有 SMB3、SMB2 FDS、音频、菜单回归通过。工程尚无这两类的实际商业游戏文件，未做新游戏实测或上板验收。固件 Release/NesFire_v0.15-mappers-preview.hex 未烧录。范围、测试及限制见 Doc/mapper_support.md。

v0.14.1 本地修正菜单手感与封面：摇杆每次拨动仅移动一项，保持拨动不连跳；回到中心区稳定 60 ms 后才能再次选择，触发/回中阈值分别为 0.65/0.25，避免阈值抖动或回弹误选。仅修改菜单，不改游戏内方向输入。标题截图保留原生 256×240，取消此前 216×203 中间缩图，LCD 只做一次最近邻放大，保持像素边缘和原图细节。原图不修改。构建零错误/零警告；真实 ARM 菜单测试覆盖长按、阈值噪声、反向回弹、短暂回中和正常再次拨动，并逐像素核对三款封面与原图的一次缩放结果。原生 Settings、输入组合键和 8 项游戏导入测试通过。当前默认构建输出为 Release/NesFire_v0.14.1-ui-preview.hex，未烧录、未上板，手感仍待用户实机体验。以下为历史版本记录。

v0.14 本地界面预览：标题画面扩大为上方 456×360 展示区，去掉封面内部重复的平台/游戏名，外部仍显示完整游戏名；用户自定义竖版海报按比例适配。游戏列表只保留 SUPER MARIO BROS. / SUPER MARIO BROS. 2 / SUPER MARIO BROS. 3。菜单按 KEY1 打开原生 SETTINGS，实时显示八个 NES 输入、摇杆原始值/就绪状态、电容键状态及音频初始化状态；长按 SW 1.5 秒返回并保留选中项。此页不载入 ROM、不执行 NES 帧；controller_test.nes 仅保留为开发测试素材，不再嵌入菜单/固件。默认 build.ps1 输出版本已同步为 0.14-ui-preview。未烧录或操作开发板，板上版本沿用先前记录。

本轮 ARM 实际 LCD 预览与边界检查、按键同时高亮/释放、KEY1 进入原生 Settings、SW 长按返回且保留选择均已通过；设置页测试会在错误调用 Nes_Load/Nes_Frame 时失败。预览文件为 Tests/nes_output/menu_smb2.png、settings_idle.png、settings_pressed.png。它们是本地仿真输出，不是板上照片。以下条目为历史版本说明。

v0.13.1 本地修正 MMC3 `$A000` 的 CIRAM 映射方向：0 对应垂直镜像（A/B/A/B），1 对应水平镜像（A/A/B/B）。此前实现和测试同时写反，导致 SMB3 底部状态栏被地面图案覆盖。新增实际 `$2007` 别名访问及游戏状态栏边框断言；截图输出同时刷新 PNG，避免显示旧预览。新固件为 `Release/NesFire_v0.13.1-mmc3-preview.hex`，仅本地构建与 Unicorn 验证，未烧录、未复位板子。详细结果见 `Doc/MMC3_display_fix_v0.13.1.md`。下面 v0.13 的 PASS 属于历史功能报告，不能作为当时画面正确的证明。

用户当前要求：后续先不下载到开发板，仅做源代码、构建与本地预览；再次烧录或上板测试前等待用户明确指示。v0.11 已在该要求到达前完成烧录与完整读回校验。

当前 v0.13-mmc3-preview 新增普通 Mapper 4 / MMC3：8 KiB PRG 两种模式、固定尾 bank、1/2 KiB CHR 布局与反转、镜像控制、PRG RAM 使能/写保护及 IRQ 寄存器。原始 `Roms/SMB3.nes`（393,232 字节，SHA-256 `6ea0777ca520ba7ad7b0ea0f6452140d59aa0b1dffe5045cb1e8020dde10c267`）已通过现有导入入口追加为第 4 项 `SUPER MARIO BROS. 3`，原三项顺序和源文件不变。SMB3 封面使用游戏真实标题画面（`Assets/posters/smb3_title.png`）；所有封面已去掉外圈边框。

真实 Keil ARM AXF 的 Unicorn 验证覆盖 SMB3 标题、1/2 人菜单、世界地图、关卡 1-1、右移、B+右加速和 B+A 跳跃；1,335 个逻辑帧中 CPU 异常与 APU 队列丢弃均为 0，PCM 范围 0～255，绘制/跳绘制后的 CPU RAM、PC 和 MMC3 状态一致。SMB3 → SMB1 → SMB2 FDS → SMB3 切换、SMB1、真实 SMB2 磁盘流程、音频、组合键、触摸 Select、调度器和导入回滚回归通过。标题、地图和关卡输出位于 `Tests/nes_output/smb3_title_menu.png`、`smb3_world_map.png`、`smb3_level1_ready.png`；第 4 项完整名称和滚动见 `menu_smb3.png`。这些都是仿真输出，不是板上照片或耳机录音。

MMC3 IRQ 使用已接受的**扫描线级 A12 近似**：背景或精灵启用时，在可见行及预渲染行时钟计数，绘制与跳绘制路径一致。它不宣称点级精确、完整 A12 上升沿资格或各 MMC3 修订版行为；后续关卡、其他 Mapper 4 游戏和长期兼容性仍需验证。本版本只完成本地构建与仿真，**未烧录、未连接 DAP/SWD、未做开发板或耳机实体验收**，板上仍为 v0.11。

v0.12 菜单进一步简化：居中封面、完整游戏名、三行选择列表和一行操作提示；移除了右侧简介、厂商/年份信息、大 START 按钮和正常设备状态徽标。错误信息仍会显示。当时游戏名称统一为 SUPER MARIO BROS.、SUPER MARIO BROS. 2、CONTROLLER TEST，不再使用 SMB2 或 PAD TEST 缩写。长名称按单词换行，不在菜单内加省略号。预览位于 Release/previews/v0.12-simple。该变更未烧录、未操作板子。

v0.12-preview 仅在本地构建，未烧录、未上板测试。界面改为 SNES 风格蓝色方框窗口、浅色像素边框、金色三角光标与四键配色；菜单、封面排版及游戏外框提示改用真正的 8x8 Press Start 2P 点阵字，以 1x/2x/3x 整数倍绘制，统一大写且无抗锯齿。游戏封面展示和选择逻辑保留。字模仅 760 字节，OFL 许可及来源保存在 Assets/fonts，生成脚本为 tools/embed_pixel_font.py。并未增加 SNES 游戏模拟功能。

v0.12-preview 当时输出为 Release/NesFire_v0.12-preview.hex。构建 0 errors / 0 warnings，主机菜单 ASan/UBSan、真实 ARM LCD 绘制边界、字体大小写映射及 1x/2x/3x 像素复制检查通过；该轮 CPU/APU 回归也通过。预览保存在 Release/previews/v0.12，属于 ARM 代码绘制到仿真 LCD 的结果，不是板子照片。

v0.11 更新菜单：深色收藏库、左侧竖版封面、右侧游戏简介和 PLAY 提示、三行滚动列表、暖色选中态与底部设备状态。方向上/下选择，KEY2 或 SW 开始；游戏内长按 SW 1.5 秒返回菜单。两款 Mario 的封面先使用游戏标题画面，加原生排版；控制器测试采用原生手柄图形。支持替换完整 PNG/JPG 海报，见 `Assets/posters/README.md`。封面数据共 88,720 字节 Flash，不分配板上菜单帧缓冲；仅增加 8 字节切换耗时诊断计数。切换不清整屏，并直接覆盖旧封面，减少闪烁。

构建和界面绘制边界测试通过；v0.11 已完成 310,272 字节完整读回校验。菜单上下循环切换的板上测试通过，Mario 封面重绘约 30.3 ms、原生手柄兜底封面约 42.1 ms，CPU/硬件异常和音频 DMA 错误均为 0。用户随后要求暂不上板，因此不再进行后续板上游戏回归。`Tests/nes_output/menu_smb1.png`、`menu_smb2.png`、`menu_pad.png` 是真实 Keil ARM 菜单代码在仿真 LCD 上的输出，不是 LCD 拍照。下述 v0.10 是此前已验收的游戏功能记录；v0.11 的新菜单上板结果另存为 `Release/board_poster_menu_v0.11.json`。

**v0.10 已烧录并通过板上基础验证**：原始 SMB2 磁碟机镜像经完整 BIOS 读盘，进入标题和 1-1；SWD 注入方向与 B+A，实测 X 从 40 移到 104、跳跃 Y 从 176 降到 136。逻辑约 60 Hz、画面约 20 Hz，CPU/硬件异常、音频 DMA 错误、队列丢弃和逻辑丢帧均为 0。用户已于 2026-11-17 确认画面、操作和声音节奏均正常，记录在 `Release/user_acceptance_v0.10.json`。

发布固件 `Release/NesFire_v0.10.hex`，完整读回校验 **218,112 字节**；报告为 `Release/dap_download_v0.10.json` 和 `Release/board_smb2_v0.10.json`。`Release/board_smb2_title.png`、`board_smb2_gameplay.png` 是板上 PPU 的 SWD 副本，不能当作 LCD 拍照。Flash 受影响扇区已备份到 `../backups/flash_20261117_084121.bin`。

镜像为用户提供的 `Super Mario Bros. 2 (Japan) (En).fds`（65,500 字节、CRC32 `F04CD4CD`、SHA-1 `20e50128742162ee47561db9e82b2836399c880c`）。BIOS 来自用户提供的 `fdsbios.nes`，实际是无 iNES 头的 8,192 字节原始 BIOS；复制为 `Roms/disksys.rom`，MD5 `ca30b50f880eb660a320674ed365ef7a`、SHA-1 `57fe1bdee955bb48d357e463ccbf129496930b62`。校验记录在 `Roms/bios.json`。旧损坏的 `fds_bios.bin` 保留，加载器仍会拒绝它（rc=9）。

已实现只读磁盘流、同步/间隙/CRC 字节生成、启动/停止/回卷、数据传输 IRQ、定时 IRQ 和镜像控制。FDS 按最多 16 个 CPU 周期分片推进；没有逐周期精度、CRC 错误检测、写盘持久化、自动多面切换或 FDS 扩展音频。**写盘会收到写保护状态，后续关卡、换盘和通关尚未验收**，目前验证范围是标题及 1-1 的基本操作。SMB2 的基础 NES APU 音乐/音效已接现有 WM8978 输出链路。

正常启动保留 BIOS 的读盘和显示流程，需要约 12～15 秒到标题，不是立即跳进游戏。无需 SD 卡；内置三项镜像总计 131,068 字节。菜单与长按 SW 返回功能保留，快照和卡带切换会还原读写分发表。

`test_fds_drive_arm.py` 通过 ARM 寄存器逐字节读回全部 18 个块 / 52,269 字节。`test_fds_foundation_arm.py` 覆盖损坏输入、IRQ、RAM 映射及切回卡带；`test_smb2_disk_arm.py` 验证真实 BIOS 启动、Start、移动、B+A 跳跃和 PCM；菜单、原版 SMB、手柄 ROM 及 260 帧音频回归均通过。完整构建为 0 errors / 0 warnings。

参考：[NESdev FDS 寄存器](https://www.nesdev.org/wiki/User:TakuikaNinja/FDS_Registers)、[Mesen FDS 行为参考](https://github.com/SourMesen/Mesen/blob/master/Core/FDS.cpp)。代码阶段备份：`../backups/Nes_before_FDS_drive_20261117.zip`。

野火 STM32F407ZGT6 霸天虎 V2、480×800 MCU 屏、HW-504 摇杆、板载 SRAM 和 WM8978 耳机输出。内置 4 个 ROM/磁盘镜像，开机先进入游戏选择菜单，选定后才加载对应镜像。当前不需要 SD 卡，更换 ROM/磁盘镜像需要重新编译烧录。

历史 v0.9 的 Workbuddy 记录称已上板下载并完整读回校验 212,992 字节，进入菜单和测试手柄；这不属于当前开发版本的上板验证。逻辑帧率与画面提交率沿用 v0.7 的调度器，不是 60 FPS 显示。

## 烧录

当前本地预览：`Release/NesFire_v0.13-mmc3-preview.hex` 和对应 BIN（均未烧录）；板上仍为 v0.11。Keil 工程：`Project/Fire_F407ZG.uvprojx`，Arm Compiler 6.24，BIN 地址 `0x08000000`。全量构建 0 errors / 0 warnings；Code=64,288、RO-data=628,472、RW-data=248、ZI-data=62,400 字节，链接 ROM 总量 693,008 字节，内部 RAM 总量 62,648 字节。文件哈希见 `Release/manifest.json` 和 `Release/mmc3_v0.13_report.json`。完整 Flash 读回和板上 SMB2 验证仅属于历史版本。更新 BIOS 后先运行 `python Nes_fire_emulator/tools/embed_fds_bios.py`，再构建。

从 BA_Game 目录执行：

```powershell
.\Nes_fire_emulator\build.ps1
.\Nes_fire_emulator\flash_dap.ps1
# 只验证
.\Nes_fire_emulator\flash_dap.ps1 -VerifyOnly
# 本机已实测的 1 MHz 下载方式
.\.tools\dap\Scripts\python.exe .\Nes_fire_emulator\tools\dap_flash.py --frequency 1000000
```

下载脚本检查发布哈希，备份受影响的完整 16/64/128 KiB Flash 扇区，单缓冲按扇区写入，逐字节读回，成功后复位。禁止自动解锁。配套 pack 使用工作区资料中的 STM32F4xx_DFP.2.15.0；兼容本机 pyOCD 的 HW/HARDWARE 复位枚举。使用下载器时关闭其他工程对同一 DAP 的访问。

## 接线与操作

| 项目 | 配置 |
|---|---|
| 摇杆 VRx | PA4，CN3-25 |
| 摇杆 VRy | PA6，CN3-21 |
| 摇杆 SW | PB7，CN3-23 |
| 摇杆电源 | 3V3 / GND，摄像头接口保持空置 |
| 扩展板 A | PC6，CN3-18，接 NES A |
| 扩展板 B | PC7，CN3-20，接 NES B |
| 扩展板 C | PE4，CN3-22，连发 A（约 6 Hz） |
| 扩展板 D | PB6，CN3-24，连发 B（约 6 Hz） |
| 扩展板 E | PE5，CN3-26，接 NES Select |
| 扩展板 F | PE6，CN3-28，菜单确认（等同 KEY2 / A） |
| 扩展板 K | 摇杆按下，沿用 PB7 / CN3-23，Start / 确认（等同 KEY2） |
| 扩展板 GND | 与板子 GND 共地；按键另一端已接 GND，内部上拉，无需外部电阻 |
| 电容按键 | PA5 / TIM2_CH1，J78 跳帽接好 |
| 耳机 | 开发板 WM8978 的 3.5 mm 耳机输出口 |

| 操作 | NES 按键 / Mario 行为 |
|---|---|
| 摇杆 | 方向 |
| KEY2 | A，跳跃 |
| KEY1 | B，加速/火球 |
| KEY1 + KEY2 | B+A，可加速跳跃 |
| SW | Start，开始/暂停 |
| 板载电容键 | Select，标题页选择 1/2 人 |
| 触屏底部左/右区 | 备用 Select/Start，坐标仍待独立实机验收 |

上电先释放摇杆和电容键，等待 `STICK READY`。未完成标定时会显示 `CENTER STICK TO CALIBRATE`。电容键状态行 `CAP ON/OFF` 与 `N` 计数会立即响应有效触摸。Select 在 Mario 关卡内不负责暂停；按 SW 暂停。依据：[任天堂官方说明书](https://www.nintendo.co.jp/clv/manuals/en/pdf/CLV-P-NAAAE_en.pdf)。

## 游戏菜单

上半区显示所选游戏的封面；列表行只显示拉丁标题（`[中文名][地区]` 前缀被去掉），完整中文名和元数据在 SELECT 打开的 GAME INFO 页。超过三项会随选中项滚动，首尾循环。缺少图片时显示原生图形和游戏名称；异常信息仍显示在底部状态行。

| 操作 | 菜单行为 |
|---|---|
| 摇杆上/下 | 移动高亮，保持拨动按 90 ms 间隔连续滚动 |
| 摇杆左/右 | 按一屏翻页，保持拨动按 150 ms 间隔连续翻页 |
| KEY2 / 摇杆 SW / 扩展板 A、F | 载入所选 ROM 并进入游戏 |
| KEY1 / 扩展板 B | 打开设置中心 |
| SELECT（扩展板 E） | 打开 GAME INFO（完整中文名和详情） |
| CAP 电容键 | 临时切换横竖屏；游戏中仍是 NES Select |
| 游戏中长按 SW 1.5 s | 静音并退回菜单 |

**SD 卡**：封面是 ROM 同目录同名的 `<文件名>.COV`，由 `tools/prepare_sd.py` 或自定义工具生成；
缺失时菜单回退到原生图形。
**全内置版本**：封面配置为 `Assets/posters/posters.json`，添加 PNG/JPG，设置 `layout: poster`，
运行 `python Nes_fire_emulator/tools/embed_posters.py` 再构建；源图保留，生成的数据只放在 Flash。
图片使用 256 色 RGB565 调色板，不需要运行期解码器。海报来源与提示词保存在 `Assets/posters/README.md`。

ROM 表来自 `Roms/roms.json`。载入前静音，成功后恢复耳机输出；失败时在菜单状态行保留错误信息。菜单不显示 mapper 和 ROM 文件名等内部细节，UART 仍保留调试记录。

### 设置中心

设置中心是全屏列表，进入游戏之前的所有页面共用 A 确认、B 返回。摇杆每次拨动只处理一次，回中稳定 60 ms 后才接受下一次拨动。

| 操作 | 行为 |
|---|---|
| 摇杆上/下 | 移动条目；AUDIO 子页选择 VOLUME 或 OUTPUT |
| 摇杆左/右 | AUDIO：音量 ±5（0–100）或切换 HEADPHONES/SPEAKER/MUTE；SCREEN：切换默认方向 |
| A / KEY2 / SW / F | 进入 CONTROL、AUDIO、SCREEN 子页，或循环当前值 |
| B / KEY1 | 返回上一层；在首页返回游戏库 |
| CONTROL 子页 | 实时显示八个按键、摇杆原始值和电容键状态，不载入 ROM |
| FAVORITE | 对库中当前选中的游戏添加或移除收藏 |

`NES/SETTINGS.BIN` 共 8 字节：版本、方向、音量、音源和 CRC32。启动时在 `NesApp_Init` 中校验并应用；删除该文件即可恢复默认（竖屏、音量 70、扬声器）。网页/PC 工具可直接读取该文件，格式见源码头文件注释。

## v0.7 修复

音频工作后，摇杆中心附近出现较大原始读数波动，旧的 256 对样本最大/最小值检查可能反复拒绝标定。现在先对每 8 对样本取均值，再使用原来的 180 计数稳定性门限；仍采集 256 对，并保留原始中心范围 1000～3100 的检查。明显偏置和持续移动不会被当作中心。

显示目标改为每 3 个逻辑帧提交一帧。绘制较慢时，调度器保留时间欠账，由后续较便宜的逻辑帧补算，避免每次全画面提交后丢失虚拟 NES 时间。仅在欠账超过 4 个周期时重同步并计数。实测恢复约 60 Hz 逻辑，用户确认音乐节奏正常。

电容键保留 v0.5 的灵敏度：TIM2 中断锁存第一次充电沿并立即停捕获，输入滤波抑制毛刺，门限为基线+50，首次有效采样触发；释放门限基线+25，连续两次确认，保持时不会重复计数。

## 声音

`User/nes/nes_apu.*` 基于用户参考工程实现双矩形、三角、噪声及参考 DMC 合成。音频经 WM8978 耳机路径输出，11,024.88 Hz、16-bit 双声道（单声道复制到左右耳），DMA1 Stream4 循环传输，半缓冲 256 个声道帧。当前使用半幅 PCM 与耳机寄存器音量 40/63，未启用板上有源蜂鸣器、喇叭功放或麦克风路径。

I2C1 控制为 PB8/PB9；I2S2 为 PB12 WS、PB13 CK、PB15 SD、PC6 MCLK，与当前摇杆及触摸屏线路不冲突。启动通信失败时显示 `AUDIO OFF` 并继续运行游戏。`tools/check_audio_board.py` 读取 codec、DMA、合成计数和逻辑帧率；最新实测 DMA 错误、音频队列丢弃、CPU 异常和逻辑丢帧均为 0，APU 半缓冲处理最大约 1.43 ms。用户已确认音乐和跳跃音效。

## 更换 ROM

**SD 卡（推荐，v0.20 起）**：直接把 `.nes` / `.fds` 文件复制到卡的 `NES` 目录，插卡开机即可，
不需要重命名、不需要索引文件、不需要在电脑上运行工具。菜单标题取自文件名（去扩展名、转大写），
所以想显示 `SUPER MARIO BROS. 3` 就把文件命名为 `Super Mario Bros. 3.nes`。
封面放同名的 `<文件名>.COV`（可省略）。最多 64 项，单个镜像普通 640 KiB、MMC5 896 KiB。
旧卡的 `G0000.NES` + `LIBRARY.IDX` 仍可启动，标题由索引提供；但新卡不再需要索引。
详见 [SD 直接放 ROM](Doc/sd_scan_v0.20.md)。

**全内置版本**（不需要卡）：`add_game.ps1 -Rom 文件路径 -Name 游戏全称 -Cover 海报路径 -Build`
一键导入并本地构建；`-Cover`、`-Build` 可省略，绝不自动烧录。完整说明见 [添加游戏](Doc/adding_games.md)。

```powershell
# 全内置：加入 ROM，重新生成、编译（不会自动烧录）
python .\Nes_fire_emulator\tools\embed_roms.py add 'D:\你的目录\游戏.nes' --label "MY GAME"
python .\Nes_fire_emulator\tools\embed_roms.py build
.\Nes_fire_emulator\build.ps1 -Embedded

# 可选：生成一包已知良好的 SD 目录（含封面）
python .\Nes_fire_emulator\tools\prepare_sd.py
```

`-Embedded` 受 768 KiB 总 ROM 预算限制；默认 SD 构建只在 Flash 内含第一款游戏作为无卡兜底。

当前卡带实现 Mapper 0、1、2、3、4、7、11、66、71，以及 FDS（Mapper 20，只读）。新增 11/66/71 只有自制 ROM 本地验证，实际游戏仍需逐款测试。Mapper 4 当前 IRQ 为扫描线级 A12 近似，不能据此宣称兼容全部 MMC3 游戏。Mapper 40 为继承的实验代码，尚不宣称支持标准 Mapper 40 游戏。工具可将受限配置的普通 NES 2.0 头转换为旧 iNES，保持 PRG/CHR 数据不变；原始 FDS 按块边界校验。列表和哈希在 `Roms/current.json`。

### 关于第二个 ROM

当前使用原始 `.fds`，详细状态见文首。旧的 `Super Mario Bros. 2 (J) (FDS Conversion).nes` 保留在 Roms，但已移出菜单；它的复位入口不能正常运行。当前 `.fds` 和完整 BIOS 已接入，并通过标题、1-1 和板上基本操作验证。

Trainer、四屏镜像、PAL、VS、PlayChoice 和其他 NES 2.0 配置拒绝加载。CPU/PPU/APU 沿用近似时序，不是逐周期精确仿真；APU 帧 IRQ / $4017 序列器未完整实现，DMC 未独立验收，同 Mapper 不保证所有游戏兼容。默认 SD 库已有带 battery 标志卡带的 8 KiB RAM 持久化，未实现即时存档、FDS 写盘或双人控制器。显示未做 TE 同步，可能撕裂；长期运行仍需进一步测试。

SD 扫描边界：只扫 `NES` 顶层目录（不递归）；最多 64 项；文件名超过 63 字符或含非 CP437 字符时，
文件仍可打开但菜单标题回退为 8.3 短名；不支持 Mapper、坏头、尺寸不符或复位向量越界的 ROM
只计入 `N SKIPPED` 并显示在状态行。

## 验证与来源

- `Tests/test_nes_arm.py`：真实 Keil ARM CPU/PPU、加载边界、手柄、换页、CHR 和 DMA 回归。
- `Tests/test_nes_games.py`：校验 ROM 表与源文件一致，逐个卡带启动 90 帧、FDS 启动 900 帧并检查 `nes_faults==0` 与颜色数，同时统计菜单绘制写入的像素数。
- `Tests/test_mmc3_arm.py`：真实 ARM 的 MMC3 PRG/CHR、SRAM、镜像、IRQ 和绘制/跳绘制回归。
- `Tests/test_smb3_arm.py`：原始 SMB3 的标题、地图、关卡、移动、B+A、PCM 和 1,335 帧状态一致性验证；`test_mmc3_switch_arm.py` 验证与 SMB1/FDS 连续切换无残留。
- `Tests/test_game_import.py`：Mapper 4 导入、完整名称、源文件保持、不支持 Mapper 与容量/封面失败回滚；`render_menu_arm.py` 检查第 4 项完整名称和滚动。
- `Tests/test_menu.c`：菜单状态机的主机端测试，覆盖循环换行、3 行滚动窗口、整屏只清一次、仅重画选中行、状态文本。
- `Tests/test_touchpad_arm.py`：真实 ARM 电容驱动、IRQ 向量、首次捕获锁存、灵敏度和组合键。
- `Tests/test_nes_audio.py`：约 439 Hz 波形、DMA 立体声输出、队列上限、260 帧实际 Mario 的 PCM 数据。
- `Tests/test_nes_scheduler.py`：模拟 35 ms 绘制帧时，真实 ARM 调度器仍完成 2 秒内约 120 个逻辑帧 /40 个绘制帧。
- `Tests/test_joystick.c` 配合 mocks 在 WSL 的 ASan/UBSan 下检查 ADC 时序、含噪声标定、移动/偏置拒绝、超时恢复和方向限幅。

Python ARM 测试依赖 `unicorn`、`pyelftools`；运行对应 Python 脚本即可。结果在 `Tests/nes_output`。其中 PPM/PNG 是 PPU 仿真或 SWD 请求的 PPU 副本，WAV 是指令仿真合成数据，都不能冒充 LCD 拍照或真实模拟音频录音。

内核来源为用户提供的 `其余资料/nes_simulate-master.zip`，原始代码在 `Reference/nes_simulate-master`；电容和音频驱动参考配套 HAL 例程，提取文件在 `Reference/board_touchpad`、`Reference/board_audio`。参考 zip 未发现明确的顶层许可证，不新增公开分发授权声明。旧小游戏 `User/game`、`User/render` 和 `Legacy` 不参与 NES 构建。历史开发记录保留于 `Doc/development_history_through_v0.5.md`，各版本烧录与硬件报告在 `Release`。

