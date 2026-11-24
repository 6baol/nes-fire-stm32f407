<p align="center">
  <img src="Doc/images/banner.png" alt="NesFire — STM32F407 NES / FDS 模拟器" width="100%">
</p>

<h1 align="center">NES Fire Emulator</h1>

<p align="center">
  <b>把红白机装进一块 STM32F407。</b><br>
  SD 卡游戏库 · 最多 2048 个 ROM · FDS / MMC5 · 横竖屏 UI · 开始画面自动成为海报
</p>

<p align="center">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-2f81f7">
  <img alt="platform" src="https://img.shields.io/badge/platform-STM32F407-46a758">
  <img alt="audio" src="https://img.shields.io/badge/audio-WM8978-a78bfa">
  <img alt="roms" src="https://img.shields.io/badge/library-up%20to%202048%20ROMs-f5a524">
</p>

> 一台能装进口袋的 NES：插卡即玩，封面自动生成，上千个 ROM 也能快速找到。

## 这是什么

NesFire 是一个运行在 **野火 STM32F407ZGT6 霸天虎 V2** 上的 NES / Famicom Disk System 模拟器。
它不只是“能跑 ROM”的固件：游戏库、封面、搜索、收藏、存档、横竖屏 UI 和音频输出，
都被做成了一个可以直接上手的掌机系统。

- **两千级游戏库**：单卡最多 2048 个 ROM，递归扫描 4 层；已实测 1550 个 ROM + 1550 个封面。
- **全速调度**：60 逻辑帧/秒，按实测耗时自动跳绘，优先保证游戏速度。
- **声音认真**：WM8978 扬声器/耳机/静音，APU + FDS + MMC5 音源。
- **画面认真**：竖屏 480×800，横屏 800×480；横屏游戏 4:3 居中，两侧信息面板。
- **封面不用愁**：没有 `.COV` 时，第一次进入游戏约 3 秒后自动截取开始画面。
- **普通人也能维护**：免 Python 的 Windows 导入助手，扫描、标记 Hack、导入、去重、排序。

## 适合谁

- **复古玩家**：插卡即玩，封面、收藏、搜索、存档齐全，不用折腾命令行。
- **硬件玩家**：野火 F407 + 480×800 屏 + WM8978，接线、按键和外壳位置都有文档。
- **嵌入式学习者**：从 6502 / PPU / APU 到 FatFs、SDIO、DMA 音频的一套完整工程。

## 亮点一览

![功能亮点](Doc/images/features.png)

## 开始使用

![从 ROM 到开玩](Doc/images/workflow.png)

1. **烧录固件**：从 [Releases](https://github.com/6baol/nes-fire-stm32f407/releases) 下载 `NesFire-1.0.hex`，烧到 `0x08000000`。固件已内置开源 FDS BIOS，NES / FDS 都可直接玩。
2. **准备 ROM**：把 `.nes` / `.fds` 放进电脑上的一个文件夹。
3. **导入 SD 卡**：运行 `NesImportGUI.exe`，选择来源和 `X:\NES`，扫描后导入。
4. **上机开玩**：插卡上电；第一次开机自动重建目录，没有封面的游戏会在首玩后自动生成海报。

完整步骤（烧录、接线、按键、常见问题）见 **[新手教程 TUTORIAL.md](TUTORIAL.md)**。

## 核心能力

### 游戏库：为“大”而生

- **2048 个 ROM 的目录**：`NES/CATALOG.IDX` 常驻 SD 卡，RAM 只保留窗口，不占住内存。
- **递归扫描 4 层**：`NES/`、`NES/imports/`、`NES/hacks/`、`NES/famicom/00/` 都能识别。
- **分桶加速**：`tools/bucket_sd.py` 每 100 个一组；路径查找从上千项降到约 100 项。
- **8 MHz SDIO + 多块读**：封面和 ROM 读取更快，末尾条目也不拖沓。
- **中文 / 拼音 / 英文搜索**：`bian`、`bianfuxia`、`bfx` 都能命中“蝙蝠侠”。
- **收藏、最近、GAME INFO**：常用游戏不用每次翻列表。

### 画面：竖屏和横屏都认真做

- 竖屏 **480×800**：上半区封面，下半区三行滚动列表，底部状态栏。
- 横屏 **800×480**：游戏保持 **640×480 居中 4:3**，不拉伸、不裁切；左右各 80 px 面板显示封面缩略图和文件名。
- **自适应绘制**：根据实测绘制/跳绘耗时调整间隔，逻辑帧仍然按 60 Hz 推进。

![界面布局](Doc/images/ui-layout.png)

### 实机界面

下面都是设备实际 LCD 输出，由离线 ARM 渲染生成：

<p align="center">
  <img src="Doc/images/device-menu-portrait.png" width="300" alt="竖屏菜单">
  <img src="Doc/images/device-menu-landscape.png" width="520" alt="横屏菜单">
</p>

<p align="center">
  <img src="Doc/images/device-settings-portrait.png" width="300" alt="竖屏设置页">
  <img src="Doc/images/device-settings-landscape.png" width="520" alt="横屏设置页">
</p>

### 声音：

- WM8978 编解码器，I2S2：扬声器、耳机、静音三种输出。
- NES APU + FDS 波表/包络/调制 + MMC5 音频。
- **PC6 固定为 I2S2_MCLK**

### 存档、收藏与设置

- 电池 SRAM 双槽存档，CRC 校验；退出游戏时写入 `NES/SAVES/`。
- `PREFS0/1.DAT` 保存收藏和最近记录；去重/分桶会自动重映射路径键。
- `SETTINGS.BIN` 保存横竖屏、音量、输出。
- 游戏运行期间不访问 SD（存档除外），避免拖慢帧率。

### 外部 ROM、Hack 与封面

- Windows 导入助手：扫描来源、标记 Hack/汉化、复制到 `NES/imports` 或 `NES/hacks`，同名不覆盖。
- 去重只按英文标题保留一个版本；**Hack、汉化、Beta、Proto、Bootleg、`[h]`、`hacks/` 永远不参与**。
- 目录重建后可按英文名排序、填充拼音。
- 没有 `.COV` 的 ROM：首玩约 3 秒（FDS 约 6 秒）自动截取开始画面，空白画面自动重试。
- 有一个我个人比较喜欢的资源库：(Ròm怀旧包 官方原版典藏包（FC/NES篇）)https://tieba.baidu.com/p/9628347423
  
<p align="center">
  <img src="Doc/images/import-gui.png" width="900" alt="NesFire 导入助手（完整窗口）">
</p>

> 导入助手的下载和详细说明见 [Doc/external_roms.md](Doc/external_roms.md)。

### FDS BIOS：开箱即用，也能一键替换

- Release 固件内置 **[OpenDiskSysROM](https://github.com/RetrolariumLab/OpenDiskSysROM)**（LGPL-3.0），FDS 游戏直接可玩，不需要原版 BIOS。
- 想换成你自己的 BIOS：**维护 → FDS BIOS → 一键导入 disksys.rom**，写入 `NES/DISKSYS.ROM`，重启游戏机后生效。
- 卡上 BIOS 优先于固件内置；文件大小或复位向量不合法时自动回退，不会把机器刷坏。

### 兼容性

| 类别 | 支持 |
|---|---|
| NES mapper | 0, 1, 2, 3, 4, 5 (MMC5), 7 (AxROM), 11, 16, 33, 40, 66, 71, 74, 117 |
| FDS | Mapper 20；换面、FDS 音源；只读磁盘；内置 OpenDiskSysROM（LGPL-3.0） |
| 存档 | 带 battery 标志卡带的 8 KiB SRAM，双槽 + CRC |
| 未实现 | MMC2/4、VRC、Namco、Sunsoft 等；PAL/VS/PlayChoice；即时存档、FDS 写盘、双人 |

> 同 mapper 不保证所有游戏兼容。完整列表和限制见 [Doc/mapper_support.md](Doc/mapper_support.md)。

### 性能：大库也跟手

- 目录常驻 SD 卡，RAM 只保留窗口；分桶后每个目录约 100 项。
- 8 MHz SDIO + 多块读，封面和 ROM 打开更快，列表末尾也不拖沓。
- 60 逻辑帧调度 + 自适应跳绘，优先保证游戏速度。
- 已用 **1550 个 ROM + 1550 个封面**的真实库验证。

### 硬件

| 项目 | 配置 |
|---|---|
| 开发板 | 野火 STM32F407ZGT6 霸天虎 V2 |
| 屏幕 | 480×800 MCU LCD |
| 音频 | WM8978，扬声器 / 3.5 mm 耳机 |
| 输入 | JoyStick Shield PS2游戏摇杆扩展板、电容键(可以自行在源码调整按键输入)|
| 存储 | SD 卡 FAT32；`NES/SAVES/` 存档 |

### 文档

| 文档 | 内容 |
|---|---|
| [TUTORIAL.md](TUTORIAL.md) | 从烧录到开玩的完整教程 |
| [Doc/external_roms.md](Doc/external_roms.md) | 导入助手、Hack、封面与目录维护 |
| [Doc/mapper_support.md](Doc/mapper_support.md) | Mapper 支持范围与限制 |
| [Doc/sd_bucketing.md](Doc/sd_bucketing.md) | 大目录分桶与封面来源 |
| [Doc/settings_centre.md](Doc/settings_centre.md) | 设置中心与横竖屏 |
| [Doc/library_details.md](Doc/library_details.md) | 游戏库、搜索与详情页 |

## 许可与素材

代码以 **MIT** 许可发布。ROM、FDS BIOS、封面和字模不属于代码许可范围；
请只使用你自己合法拥有的文件。Release 提供不含商业 ROM/原版 BIOS 的干净固件，
其中 FDS BIOS 为 OpenDiskSysROM（LGPL-3.0），源码与许可证随源码包提供。
