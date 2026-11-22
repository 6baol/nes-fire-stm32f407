# Mapper 支持范围（v0.19，本地开发版）

v0.19 更新：新增 Mapper 5 / MMC5 的受限 8 KiB WRAM 配置，PRG ≤512 KiB、CHR ROM ≤256 KiB，单镜像 ≤896 KiB。恶魔城 III（USA）及 Just Breed（Japan）的本地实际游戏验收、尚未覆盖的 PCM 读模式和大 RAM 板型等限制见 [mmc5_v0.19.md](mmc5_v0.19.md)。以下“不支持 MMC5”仅为 v0.18 当时的历史状态。

日期：2026-11-19。本轮仅离线开发。完整新增说明见 [mappers_v0.18.md](mappers_v0.18.md)。

| 类型 | 本轮支持范围 | 验证程度 |
|---|---|---|
| 11 / Color Dreams | PRG 32～128 KiB，CHR ROM 8～128 KiB，均为 2 的幂；32 KiB PRG / 8 KiB CHR 换页；固定 H/V；旧 iNES 无冲突策略 | 自制 ROM 的实际 ARM 执行及 SD FAT32 加载通过；无对应商业游戏与实机验收 |
| 66 / GxROM | PRG 32～128 KiB，CHR ROM 8～32 KiB，均为 2 的幂；标准 GNROM/MHROM 位布局；固定 H/V；总线 AND 冲突，RMW 两次写入 | 同上 |
| 71 / Camerica | PRG 32～256 KiB，2 的幂；8 KiB CHR RAM；低端 16 KiB 换页、高端固定尾 bank；旧 iNES 下 $9000～$9FFF 首写切换单屏 | 同上 |

三类均不提供 PRG RAM；拒绝 battery 标志及非零 iNES PRG RAM 字段。未接硬件的 $6000～$7FFF 读取确定性返回 0，并非精确开放总线。11/66 采用初始 32 KiB bank 0，71 为低端 bank 0 / 高端最后 bank。NES 2.0 显式子 Mapper 仍拒绝；受限普通 submapper 0 可由导入器转换。11 不支持依赖总线冲突的特殊程序；66 不含超规格扩容板；71 不含 Mapper 232 Quattro 外层换页。

当前已实现卡带 0、1、2、3、4、7、11、66、71，FDS 为 20；40 保留历史实验入口，不能视作标准 Mapper 40 兼容。MMC5（5）、MMC2/4（9/10）、VRC 系列、Namco、Sunsoft 等仍未实现。下文为 v0.15 及后续历史验收记录。

更新（v0.17.5）：默认 SD 库已支持带 battery 标志卡带的 8 KiB PRG RAM 双槽持久化；FDS 增加换面与波表/包络/调制音源，仍未写盘。见 [saves_fds_v0.17.5.md](saves_fds_v0.17.5.md)。下文“没有持久化”及 v0.15 验收范围保留为历史记录，MMC1/AxROM 的板型限制仍适用。

更新（2026-11-18 / v0.16）：用户提供的 Metroid (USA) 与 Wizards & Warriors (U) 已分别完成 Mapper 1/7 的真实游戏本地 ARM 验证：标题、开始、进入场景、移动、跳跃、PCM。已加入五款游戏列表，报告见 `Tests/nes_output/mmc1_axrom_games_results.json`。仍未上板；后续关卡、存档与耳机实听未验收。以下“没有商业游戏验收”仅描述 v0.15 当时状态。

日期：2026-11-17。未烧录、未操作 DAP/SWD、未复位开发板。菜单仍为三款 Mario，未将自制测试 ROM 加入游戏库。

## 新增实现

| 类型 | 支持范围 | 验证范围 |
|---|---|---|
| Mapper 1 / MMC1B 基础配置 | PRG 为 16～256 KiB、2 的幂；CHR ROM 8～128 KiB、2 的幂，或 8 KiB CHR RAM；单个 8 KiB PRG RAM | 自制 ROM 在真实 Keil ARM AXF 下执行；没有商业游戏验收 |
| Mapper 7 / AxROM | PRG 为 32～256 KiB、2 的幂；8 KiB CHR RAM；无 PRG RAM / 电池标志 | 自制 ROM 在真实 Keil ARM AXF 下执行；没有商业游戏验收 |

导入入口依旧是 `add_game.ps1 -Rom '文件路径' -Name 'FULL GAME NAME'`，也可先用 `python tools/embed_roms.py check '文件路径'` 只读检查。命令相对于工程目录。文件通过格式检查不等于游戏兼容性验收。最终是否能与现有 ROM/封面一起嵌入，仍须检查镜像预算与 Keil 链接占用。

### MMC1

- 数据低位先行，五次串行写入提交；由第五次地址选择目标寄存器。D7 复位丢弃部分写入并将 Control OR `$0C`，保留 CHR 模式和镜像位。
- PRG 的两种 32 KiB 模式、固定低端/高端 16 KiB 模式；CHR 的 8 KiB / 独立 4 KiB 模式，原始 CHR 与解码缓存同步更新。
- Control 的镜像值 0/1/2/3 分别对应 A/A/A/A、B/B/B/B、A/B/A/B、A/A/B/B。
- PRG 寄存器 D4 禁用 RAM；支持当前单 CHR RAM 配置的 CHR0 D4 附加禁用门。禁用时读取确定性返回 0，尚未模拟 CPU 开放总线电平。
- 既有 CPU 内核只发出读改写指令的最终写入。新增 RMW 注记保存真正的原始字节，在 MMC1 端重建第一次写入，抑制第二次 D0 数据，但仍接受第二次 D7 复位。覆盖全部 12 种合法绝对/绝对 X 的 ASL/ROL/LSR/ROR/DEC/INC；RAM/其他 mapper 保持原路径。不靠猜测 PC 前面的操作码判断 RMW。
- 不支持 MMC1A 特有行为、固定 PRG 板型的全部差异、SUROM/SOROM/SXROM 外层 PRG/RAM 换页、MMC1 衍生 mapper、依赖未实现非法 CPU 指令的程序，亦不宣称完整芯片级时序。
- **电池存档未持久化**：PRG RAM 仅在运行中存在，加载游戏时会清零，断电也会丢失。接受 battery 头部标志不表示已经支持保存/恢复存档。

### AxROM

- D0～D2 选择 32 KiB PRG，D4 选择单屏 A/B；8 KiB CHR RAM 可写。
- 开机选择 bank 0，因此加载器和导入器均检查第一个 32 KiB 中的复位向量，不再误用整个 PRG 尾部向量。
- iNES 未指定冲突板型按无 bus conflict 处理；NES 2.0 特殊 submapper 仍由现有校验拒绝。不宣称支持强制 AND 总线冲突变种。

寄存器行为参考：[NESdev MMC1](https://www.nesdev.org/wiki/MMC1)、[NESdev AxROM](https://www.nesdev.org/wiki/AxROM)。未下载或嵌入第三方商业游戏文件。

## 验证与产物

从 `D:\Project\BA_Game` 运行：

```powershell
.\Nes_fire_emulator\build.ps1 -Version '0.15-mappers-preview'
python .\Nes_fire_emulator\Tests\test_mmc1_axrom_arm.py
python .\Nes_fire_emulator\Tests\test_game_import.py
python .\Nes_fire_emulator\Tests\test_nes_arm.py
python .\Nes_fire_emulator\Tests\test_mmc3_arm.py
python .\Nes_fire_emulator\Tests\test_mmc3_switch_arm.py
python .\Nes_fire_emulator\Tests\test_smb3_arm.py
python .\Nes_fire_emulator\Tests\test_smb2_disk_arm.py
python .\Nes_fire_emulator\Tests\test_nes_audio.py
python .\Nes_fire_emulator\Tests\render_menu_arm.py
```

上述本轮均通过：全量构建 0 errors / 0 warnings；新增 8 组 ARM 专项测试，导入 9 项测试；既有 CPU/PPU、MMC3、SMB3 状态栏及移动跳跃/PCM、SMB2 BIOS/磁盘到 1-1、APU、跨游戏切换、菜单/Settings/防误选与封面像素核对回归。新增商业游戏与耳机/开发板性能未验收。

专项报告：`Tests/nes_output/mmc1_axrom_results.json`；发布固件：`Release/NesFire_v0.15-mappers-preview.hex` / `.bin`。版本报告：`Release/mappers_v0.15_report.json`。

实现入口：`User/nes/mapper/001.cpp`、`007.cpp`；公共接点：`nes_main.c`、`nes_mapper.c`、`6502.s`、`6502mac.s`；导入检查：`tools/embed_roms.py`。
