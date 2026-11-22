# Mapper 扩展 v0.18（2026-11-19，离线开发）

新增 Color Dreams（11）、标准 GxROM（66）、Camerica（71）。版本 `0.18-mappers-preview`；本轮没有操作仿真器、烧录、复位开发板或写入物理 SD 卡。五款既有游戏和封面保留，自制测试 ROM 不加入用户菜单。默认声音仍为扬声器。

## 实现与限制

| Mapper | PRG | CHR | 寄存器与镜像 |
|---|---|---|---|
| 11 / Color Dreams | 32～128 KiB，32 KiB 整窗换页 | 8～128 KiB ROM，8 KiB 换页 | `$8000～$FFFF`，D0～D1 选 PRG、D4～D7 选 CHR；固定头部 H/V |
| 66 / GxROM | 32～128 KiB，32 KiB 整窗换页 | 8～32 KiB ROM，8 KiB 换页 | `$8000～$FFFF`，D4～D5 选 PRG、D0～D1 选 CHR；固定头部 H/V |
| 71 / Camerica | 32～256 KiB，低端 16 KiB 换页、高端固定最后 16 KiB | 8 KiB RAM，不换页 | `$C000～$FFFF` 的 D0～D3 选 PRG；`$9000～$9FFF` 的 D4 选单屏 A/B |

容量均须为 2 的幂。三者没有 PRG RAM，固件及导入器拒绝 battery 标志、非零 iNES PRG RAM 字段、Trainer、四屏、PAL 等不支持的配置。无 RAM 的 `$6000～$7FFF` 写入被忽略、读取返回 0；未实现精确开放总线。

11/66 冷加载统一从第一个 32 KiB PRG bank、CHR bank 0 启动，并检查该 bank 中的复位向量。71 从低端 bank 0、高端最后 bank 启动，检查尾 bank 的向量。CHR 原始 bank 指针与解码 tile 指针同时更新，未接的地址线通过容量掩码回绕。

11 对旧 iNES 采用无总线冲突约定，与既有 AxROM 策略相同；依赖冲突的特殊程序不在本次范围。66 按标准板模拟 `CPU 写值 AND 当前 PRG 字节`，在改变映射前读取旧 bank；6502 读改写指令重建第一次写入，再以已切换的映射处理第二次冲突。71 无总线冲突；旧 iNES 没有子 Mapper 信息，采用兼容约定：保留头部 H/V，忽略 `$8000～$8FFF`，首次写 `$9000～$9FFF` 后才转为 Fire Hawk 单屏控制。未实现 66 超规格扩容板或 232 Quattro 外层换页。

依据：[Color Dreams 寄存器](https://www.nesdev.org/wiki/Color_Dreams)、[旧 iNES 的冲突约定](https://www.nesdev.org/wiki/Submapper)、[GxROM 寄存器](https://www.nesdev.org/wiki/INES_Mapper_066)、[Camerica / Fire Hawk 兼容约定](https://www.nesdev.org/wiki/INES_Mapper_071)。按这些资料实现并自行编写测试，不以第三方模拟器的 PASS 作为本工程验收。

导入器、SD `LIBRARY.IDX` 白名单、实际 `Nes_Load` 板型校验均已同步。额外修正普通 NES 2.0 转换的既有漏洞：原先只检查 byte 8 低半字节，会丢弃高半字节的显式 submapper。现在要求整个 byte 8 为 0，避免把硬件变体误转为默认板型。受限普通 submapper 0 转换仍保持 PRG/CHR 逐字节不变。

## 本地验证

- 全量 Keil 编译：0 errors、0 warnings。Code 92,816 / RO 56,344 / RW 276 / ZI 79,084 字节；BIN 150,528 字节，相比 v0.17.7 增加 1,024 字节，ZI 不变。
- `test_discrete_mappers_arm.py`：7 组实际 ARM 内核专项，覆盖全部 256 个寄存器值、PRG/CHR 容量回绕、原始/解码 CHR、DMC 当前映射读取、总线冲突与地址别名、真实 6502 跨页续执行、复位向量、66 RMW、71 PPU 镜像别名及 CHR RAM、无 SRAM、FDS/卡带切换、非法板型拒绝。
- `test_discrete_mappers_sd_arm.py`：三种自制卡带经实际 ARM FatFs 读取内存 FAT32 的索引、CRC、预加载、CPU 执行与换页；游戏帧内无 SD I/O、无写卡。
- `test_game_import.py`：14 项通过，含新三类源文件保持、错误板型回滚、NES 2.0 转换及显式子 Mapper 拒绝。
- 既有 14 个回归脚本通过：MMC1/AxROM、MMC3 与跨游戏切换、NMI、SD 库及双槽存档、音频路由/静音、FDS 驱动/换面/音源、SD 游戏流程、Wizards 连续画面及菜单。SD 库覆盖五款加载；完整游戏流程覆盖 SMB3、SMB2 FDS、Metroid、Wizards，不能等同于所有关卡验收。

报告：`Release/mappers_v0.18_report.json`；专项及回归细节在 `Tests/nes_output/discrete_mappers_results.json`、`discrete_mappers_sd_results.json`、`mapper_regression_core.json`、`mapper_regression_games.json`、`mapper_import_v0.18.log`。报告记录当前 AXF 哈希。

可复现命令（工程目录）：

```powershell
.\build.ps1
python Tests/test_discrete_mappers_arm.py
python Tests/test_discrete_mappers_sd_arm.py
python Tests/test_game_import.py
```

## 添加实际游戏

```powershell
python tools/embed_roms.py check 'D:\Games\game.nes'
.\add_game.ps1 -Rom 'D:\Games\game.nes' -Name 'FULL GAME NAME' -Cover 'D:\Games\cover.png' -Build
```

`-Cover` 可省略；生成本机 `Release/SD_ROOT/NES` 后仍须按既有步骤安装到 SD 卡。正常导入格式检查不等于游戏可玩性验收。本轮没有三类对应的商业游戏，尚未实机验证性能、音画和长期运行；不将自制测试结果标记为商业游戏兼容。

MMC5（5）、MMC2/4（9/10）、VRC 系列、Namco 和 Sunsoft 等仍未实现。Mapper 40 保留继承的实验入口，不属于标准 Mapper 40 已兼容清单。
