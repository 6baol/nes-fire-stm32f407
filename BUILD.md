# 从源码构建 NesFire

## 包含什么

- STM32F407 固件源码、Keil 工程、工具和文档。
- 原创 **CONTROLLER TEST** 回退 ROM（公开测试卡带）。
- **OpenDiskSysROM**（LGPL-3.0）FDS BIOS 源码和 8 KiB `disksys.rom`。
- 不含商业 ROM、原版 FDS BIOS 或商业封面。

## 构建

1. 安装 Keil 5 和 **Arm Compiler 6.24**。
2. 打开 `Project/Fire_F407ZG.uvprojx`。
3. 全量 Build，产物在 `Project/Output/Fire_F407ZG.hex`。
4. 烧录地址 `0x08000000`。

## 运行

- SD 卡格式化为 FAT32，根目录建 `NES/`。
- 把 `.nes` / `.fds` 放进 `NES/` 或子目录（递归 4 层）。
- 第一次开机会自动重建 `NES/CATALOG.IDX`。
- 固件已内置 OpenDiskSysROM，FDS 可以直接运行。

## 换成你自己的 FDS BIOS

- **不用重编译（推荐）**：把 8192 字节的 `disksys.rom` 放到 SD 卡
  `NES/DISKSYS.ROM`，或在导入助手里 **维护 → FDS BIOS → 一键导入**；
  重启后生效。卡上 BIOS 优先于固件内置。
- **内置到固件**：把 `disksys.rom` 放到 `Roms/`，运行
  `python tools/embed_fds_bios.py`，再 Build。

## 加入自己的游戏（可选）

- 把 ROM 放进 `Roms/`，编辑 `Roms/roms.json`（`file` + `label`），
  运行 `python tools/embed_roms.py`，再 Build。
- 或者不重新编译，直接把 ROM 放进 SD 卡 `NES/`，固件会扫描。

## 封面

- SD 卡：ROM 同目录同名的 `<文件名>.COV`；缺失时首玩 3 秒后自动截取。
- 内置封面（可选）：`Assets/posters/posters.json` +
  `python tools/embed_posters.py`。

## 工具依赖

```powershell
pip install pillow pypinyin
```

## 第三方

- **OpenDiskSysROM** — Famicom Disk System BIOS 重实现，LGPL-3.0。
  源码：<https://github.com/RetrolariumLab/OpenDiskSysROM>
  许可证和源码随源码包放在 `third_party/OpenDiskSysROM/`。
- STM32 HAL / CMSIS、FatFs 的许可证见 `LICENSE` 和各自源码头。
