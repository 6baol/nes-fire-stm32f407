# 16 GB SD 卡接入准备（2026-11-18）

**已由 v0.17 实现取代，当前说明见 [SD_card_v0.17.md](SD_card_v0.17.md)。** 当前固件已经接入 SD；本文保留早期规划。特别注意：早期规划遗漏了旧 FDS 合成流也使用 `0x6C060000`，直接照旧内存计划会冲突。v0.17 SD 构建已将 FDS 流移到 `0x6C0E0000`，且通过磁盘从 SD 加载到 1-1 的回归。下文“未实现”与旧内存分配仅指准备阶段，不可用作当前接入结论。

## 更新：电脑读卡器中的资源已就位

已通过当前磁盘枚举确认用户卡为 F:，FAT32，容量约 15.42 GiB。已新增 `F:\NES`，复制 13 个文件、共 927056 字节，并逐文件读取计算 SHA-256，与本机资源包一致。原有 `TH06`、`System Volume Information` 保留，没有格式化或覆盖已有文件。记录在 `Release/sd_copy_v0.16.json`。仍未访问开发板；固件 SD 加载器尚未集成。以下“盘符未确认/未写卡”描述此前准备阶段。

## 当前已完成与未完成

- v0.16 五款游戏仍以内置 Flash 方式运行，构建通过，**没有 SD 固件加载功能**。
- 已生成本机 `Release/SD_ROOT/NES`，没有探测、格式化、写入用户卡，也没有连接/操作开发板。
- SD 包含五款镜像、五款原生标题封面、8 KiB BIOS、`INDEX.TSV` 和带 SHA-256 的 `GAMES.JSON`。`.nes` 仅做与既有导入器相同的兼容头部规范化，原始 Roms 文件不修改。
- 卡的当前位置、盘符、文件系统尚未由用户确认。其他工程历史文档中的 F: 不能视为当前卡的盘符。

## 已查到的本地参考

同工作区 `Touhou_Embedded/User/sdio/bsp_sdio.c` 与 `User/fatfs` 已有针对同款霸天虎 V2 的轮询 SDIO / FatFs R0.16 接入代码。其文档标明固件编译通过但 SD 路径未上板验收，不能当作本模拟器已验证的驱动。

板载 MicroSD 的 SDIO 引脚：PC8～PC11 数据，PC12 时钟，PD2 命令。与摇杆 PA4/PA6/PB7、耳机 I2S 的现有引脚无直接冲突。PC8/PC9 与摄像头接口复用，继续保持摄像头断开。本地板卡资料列 SD 卡支持至 32 GB，用户 16 GB 卡在该范围。

拟采用 FAT32、只读挂载。现有参考 FatFs 配置关闭 exFAT 和长文件名，资源目录因此使用 8.3 文件名，屏幕显示的完整游戏名保存于索引。无需先格式化卡；若卡已是 FAT32，后续可以直接使用，确认状态前不操作分区或现有文件。

## 资源目录

```text
SD_ROOT/
  NES/
    INDEX.TSV
    GAMES.JSON
    DISKSYS.ROM
    G0000.NES + G0000.COV   SUPER MARIO BROS.
    G0001.FDS + G0001.COV   SUPER MARIO BROS. 2
    G0002.NES + G0002.COV   SUPER MARIO BROS. 3
    G0003.NES + G0003.COV   METROID
    G0004.NES + G0004.COV   WIZARDS & WARRIORS
```

从 `D:\Project\BA_Game` 重新生成本机目录：

```powershell
python .\Nes_fire_emulator\tools\prepare_sd.py
python .\Nes_fire_emulator\Tests\test_sd_pack.py
```

默认输出仅为工程的 Release/SD_ROOT。工具支持 `--output`，但本轮没有指定用户盘符或向读卡器写文件。现阶段把这个目录复制到卡上也不会让 v0.16 自动读卡；需先完成固件接入。

封面 COV 是小端 NCV1：24 字节头（magic、宽/高、索引位数、flags、调色板项数、调色板字节数、像素字节数、payload CRC32），接 RGB565 调色板及 4/8 位索引像素。4 位数据高半字节在前，奇数像素末尾低半字节补零。Python 编解码和截断/CRC 拒绝测试已通过；尚无板载 COV 文件读取代码。

## 后续固件接入约束

1. 增加 SDIO/FatFs、游戏库索引和动态加载入口。先准备 ROM，再调用既有 Nes_Load；不要在运行 6502 的热路径中逐字节读卡。
2. 利用 1 MiB 外扩 SRAM 缓存当前游戏；16 GB 是游戏库容量，并不扩大 SRAM 或自动增加 Mapper 支持。
3. 现有 CHR 原始区 `0x6C000000～0x6C020000`、解码区 `0x6C020000～0x6C040000`；截图缓存为 `0x6C040000～0x6C05E000`。可评估 `0x6C060000～0x6C100000` 的 640 KiB 作为 ROM 预载区；必须明确大小检查，不能覆盖 CHR/截图。封面缓冲与 ROM 共享需限制为菜单/游戏互斥时段。
4. 内核仍有单镜像大小、Mapper、NTSC 和 FDS 单面只读限制；SD 不解除这些条件。PRG 从外扩 SRAM 执行取指的性能须实机测量，不能承诺与 Flash 同速。
5. 先用文件/坏卡仿真验证无卡、坏索引、短读、校验失败和超大镜像，再在用户明确要求后进行上板测试。
6. 当前不增加写盘、自动格式化或存档写入；若后续要保存电池 RAM，应单独实现写入/恢复与异常处理。

接入完成后才可把 ROM/封面从内部 Flash 发布版本移除。当前五款游戏仍可作为不依赖 SD 的本地基线，不会因为准备卡目录而失去现有运行方式。
