# MMC5 v0.19 本地开发版

实机验收更新（2026-11-19）：用户自行烧录 v0.19 后，确认恶魔城 III（USA）的画面、方向/跳跃/攻击和声音正常；Just Breed（Japan）的开场文字、城镇画面和音乐正常。运行中只读 Flash 全量比对一致，菜单识别七款游戏、扬声器路由及错误计数正常。本轮没有下载、复位或注入按键。验收只覆盖上述基本流程；游戏实测帧率、后续章节、长期运行及板上存档冷恢复未验证。记录见 `Release/user_acceptance_v0.19.json`；下文未上板等表述保留为开发阶段记录。

2026-11-19。新增 Mapper 5，已将用户提供的两款游戏加入原有五款之后，保留完整名称和源文件。开发板未烧录、未复位。F: 的 16 GB FAT32 卡已安装新增资源，旧 ROM、封面、存档及 TH06 保留；旧索引已备份。

## 本次范围

- 4 种 PRG 模式、4 种 CHR 模式，背景与 8×16 精灵分别选 CHR；高位 CHR 寄存器在写入时锁存。
- 8 KiB WRAM、RAM/ROM 窗口切换与双寄存器写保护；沿用 SD 的 CRC 双槽存档。
- ExRAM、逐图块扩展属性、四个名称表分别选源、填充模式、8×8 乘法器。
- 扫描线 IRQ、状态读取确认和开关控制；按当前逐扫描线内核近似计时。
- 垂直分屏的按图块渲染路径已接入，但没有对应商业游戏验收。
- 两路脉冲声道：占空比、周期、音量/包络、240 Hz 长度计数；直接写入 PCM。CPU 状态与音频混合状态分离，通过既有时间戳队列同步。
- 修正旧 6502 的 `JMP ($6xxx)` 换算：表索引是字节偏移 12，原代码误与 3 比较，导致 Just Breed 从 WRAM 读取跳转目标时跳到零页。增加实际 CPU 回归。
- 修正低地址 Mapper 寄存器换页后正在执行的 PC 映射刷新。

实现依据：[MMC5 寄存器与 CHR/IRQ](https://www.nesdev.org/wiki/MMC5)、[MMC5 音源](https://www.nesdev.org/wiki/MMC5_audio)。本项目仍是扫描线级模拟，不宣称芯片级完全兼容。

## 容量与内存

本次板型限定 PRG ≤512 KiB、CHR ROM ≤256 KiB，均为 2 的幂，WRAM ≤8 KiB。受限 NES 2.0 头可转换：额外允许 MMC5 单个 8 KiB PRG RAM 或 NVRAM；显式 submapper、额外设备等仍拒绝。转换仅改头部，原始文件和 PRG/CHR 载荷不改。

| 用途 | MMC5 地址/范围 |
|---|---|
| 预加载 ROM（含原始 CHR） | `0x6c020000`，最多 896 KiB |
| 解码 tile cache | `0x6c000000`，256 项，共 4 KiB；每项校验源 tile 标签 |
| 8 KiB WRAM | 既有 `NES_SRAM`，可持久化 |
| 原有 640 KiB arena | 其他 Mapper 继续使用，封面仍在菜单时加载 |

Just Breed 的 786,448 字节镜像无需逐帧读卡。MMC5 运行时禁止向原 `0x6c040000` 整帧诊断缓冲区写入，避免覆盖 ROM；LCD 正常输出不受影响。实际 ARM `NesPort_Line` 已测试捕获请求被清除且 ROM 字节不变。

## 游戏验证

| 游戏 | 本地实际 ARM / FatFs 验证 |
|---|---|
| Castlevania III: Dracula's Curse（USA） | 标题、姓名页、进入 1-01；OAM 验证右移 >15 px、A 跳跃抬高 >12 px；PCM 非静音；CPU 错误和音频队列丢弃为 0 |
| Just Breed（Japan） | 存档选择、姓名输入、开场文字和城镇剧情；实际扩展音源写入、PCM 非静音；游戏写入的 8 KiB WRAM 保存并冷加载逐字节恢复；CPU 错误和队列丢弃为 0 |

两款都经过真实编译 ARM FatFs 的内存 FAT32：索引、CRC、整镜像预载；帧内无 SD I/O，运行后 ROM 载荷逐字节不变。Just Breed 的自由移动、战斗和后续流程未验收，不把剧情场景测试当作通关证明。

专项 `Tests/test_mmc5_arm.py` 共 6 组，覆盖换页后 CPU 续执行、RAM 保护与间接跳转、CHR/cache、ExRAM/填充/IRQ/乘法器、扩展音源和诊断截图防覆盖。旧 Mapper、CPU/PPU、FDS、存档、音频及既有游戏回归通过；七款库和原生菜单的完整名称、滚动及封面像素检查通过。

全量构建 0 errors / 0 warnings；Code 98,208 / RO 56,348 / RW 276 / ZI 83,308 字节；BIN 155,648 字节。最终七款资源构建的 AXF 含更新后的调试信息，BIN/HEX 与两款游戏完整验证时逐字节一致；报告分别保留测试 AXF 和最终 AXF 哈希，不将旧测试记录改写为新 AXF 实测。

## 尚未覆盖

- PCM 读模式的 CPU 读监听和 PCM IRQ；MMC5A 额外寄存器。
- 多芯片/大于 8 KiB WRAM 的板型、其 bank 选择细节及存档。
- 更大 PRG/CHR、精确开放总线、点级 PPU/IRQ 时序、所有分屏边界行为。
- 实机帧率、声音比例和长期运行；其余 MMC5 游戏。

## 使用

1. 安全弹出 F:，把 SD 卡插回板上。
2. 手动烧录 `Release/NesFire_v0.19-mmc5-preview.hex`（默认 SD 工程）。
3. 菜单第 6 项为恶魔城 III，第 7 项为 Just Breed；默认仍为扬声器。

旧 v0.18 及更早固件不接受含 Mapper 5 的新索引，会回退内置游戏，必须配套 v0.19。Just Breed 为日文原版，进入新游戏须填写姓名；KEY2=A，KEY1=B，摇杆 SW=Start。

安装记录：`Release/sd_install_v0.19.json`；旧索引备份目录记录于该 JSON 的 `metadata_backup`。开发板没有由本轮工具烧录，固件报告的 `hardware_tested` 保持 false。总报告：`Release/mmc5_v0.19_report.json`。
