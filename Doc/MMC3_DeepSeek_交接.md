# MMC3 / Super Mario Bros. 3 开发交接

交接日期：2026-11-17。接手对象：DeepSeek。工程根目录：`D:\Project\BA_Game\Nes_fire_emulator`。

## 1. 可以直接发送给 DeepSeek 的任务说明

> 请接手当前 STM32F407 NES 模拟器，为用户提供的 `Roms/SMB3.nes` 实现 Mapper 4（MMC3），完成本地编译、真实 ARM 内核仿真测试和回归，再将游戏以完整名称 `SUPER MARIO BROS. 3` 接入现有游戏菜单。
>
> **用户明确要求暂不上板。只修改文件、本地编译和仿真；不要下载固件，不要连接或操作 DAP/SWD，不要复位开发板，不要运行任何板上采样或自动按键脚本。** 本次交付应标为未烧录、未做实机验收，之后上板须等用户明确指示。
>
> 请先阅读本交接文档和当前源码。保留现有简洁像素菜单、完整游戏名、封面机制、游戏导入工具，以及已工作的 SMB1、SMB2 FDS、输入和耳机声音。不要通过改 ROM 头、跳过断言、屏蔽 CPU 错误或直接跳入关卡来绕过实现。重点检查初始化顺序、8 KiB PRG 切换后的取指、CHR 原始/解码缓存同步、MMC3 IRQ 与跳帧路径。完成后给出修改文件、可复现命令、测试结果、截图及仍有的兼容性限制。

## 2. 当前状态与任务边界

| 项目 | 已有状态 / 本次要求 |
|---|---|
| 板上版本 | v0.11；用户要求暂不上板后未继续操作硬件 |
| 当前本地版本 | v0.12-preview，Keil 输出已存在；本地构建与仿真结果不能称为实机结果 |
| 界面 | NES/SNES 风格像素字、蓝色窗口、居中封面、完整游戏名、三行滚动列表；这里的 SNES 仅指视觉风格 |
| 当前菜单 | `SUPER MARIO BROS.`、`SUPER MARIO BROS. 2`、`CONTROLLER TEST` |
| 当前卡带支持 | Mapper 0、2、3；40 是继承的实验实现，兼容性未验收 |
| FDS | Mapper 20，完整 BIOS + SMB2 单面只读磁盘；用户此前确认画面、操作、声音正常 |
| 新目标 | 实现并验证普通 MMC3，优先让当前 SMB3 正常启动、进入地图/关卡、操作和播放声音 |
| 不扩展的任务 | 不重写界面，不加入 SNES 模拟，不更换输入/音频硬件，不顺带实现 MMC6、全部 MMC3 衍生板或 FDS 写盘 |
| SD 卡 | 本目标先沿用内部 Flash 嵌入 ROM，无需先加 SD；最终占用以链接结果为准 |

工程不是全新移植起点。请在当前源码上增量开发，不要用旧压缩包、Workbuddy 历史说明或旧备份覆盖现有功能。`README.md` 下部留有早期操作说明；版本与不上板约束以本文及 README 顶部为准。

### 硬件与运行节奏（供理解约束）

- STM32F407ZGT6，168 MHz，内部 Flash 1 MiB；480×800 MCU LCD；外部 SRAM 1 MiB，基址 `0x6C000000`。
- HW504 摇杆：VRx=PA4、VRy=PA6、SW=PB7。KEY2=A，KEY1=B，必须保留 B+A 同按；SW=Start，长按返回菜单。
- 电容键 PA5 / TIM2_CH1，J78 已插好，作为 Select，用户已确认轻触响应正常。
- WM8978 耳机输出已经工作，11025 Hz，单声道 PCM 复制到双声道 DMA。无需使用板载有源蜂鸣器。
- 逻辑约 60 Hz，默认每 3 个逻辑帧绘制一次，显示约 20 Hz。不要为追求声音或 IRQ 正确性随意改变全局速度；`Nes_Frame(0)` 也必须正确推进模拟。
- FDS 的 CPU 执行采用不超过 16 周期的分片，以及时处理读盘 IRQ，须保留。

## 3. 用户提供的 SMB3 文件

| 字段 | 当前实际读取结果 |
|---|---|
| 文件 | `D:\Project\BA_Game\Nes_fire_emulator\Roms\SMB3.nes` |
| 长度 | 393,232 字节 |
| 16 字节头 | `4e45531a101040000000000000000000` |
| 格式 | iNES 1，Mapper 4；不是 FDS，也不是 NES 2.0 |
| PRG ROM | 262,144 字节，32 个 8 KiB bank |
| CHR ROM | 131,072 字节，128 个 1 KiB bank |
| 头部标志 | 初始水平镜像；无 trainer、battery、four-screen 标志 |
| 末尾 PRG 复位向量 | `$FF40` |
| SHA-256 | `6ea0777ca520ba7ad7b0ea0f6452140d59aa0b1dffe5045cb1e8020dde10c267` |

该文件目前仅保存在 Roms，**没有加入菜单**。`embed_roms.py check` 会报 `Unsupported mapper 4`，这符合当前实现状态。

现有三项镜像共 131,068 字节，加入 SMB3 后镜像总计 524,300 字节，小于导入器的 768 KiB 镜像预算；代码、BIOS、字体、封面也占 Flash，仍须检查 Keil 最终链接占用。不要将镜像预算当作固件最终大小保证。

## 4. 代码入口与必须检查的接点

下面路径均相对于工程根目录，先读源码再修改。

| 文件 | 与 MMC3 的关系 |
|---|---|
| `User/nes/nes_main.c` | `Nes_Load` 格式/容量校验，初始化顺序，`Nes_Frame` 时序，`nes_run_cycles`，`Nes_ApuReadDmc` |
| `User/nes/nes_mapper.c` / `.h` | Mapper 注册表、回调、CPU/PPU bank 包装函数 |
| `User/nes/mapper/000.cpp`、`002.cpp`、`003.cpp`、`020.cpp`、`040.cpp` | 现有 mapper；020 是 FDS，040 不是可直接照搬的 MMC3 |
| `User/nes/cart.s` | PRG 映射、`cpu6502_init`、编码 PC 的 `flush` |
| `User/nes/6502.s` | 实际 6502 执行器、CPU IRQ、SRAM 读写、C/ASM 桥接 |
| `User/nes/nes_ppu.c` | 扫描线绘制/跳绘制、CHR 访问和解码图块缓存 |
| `tools/embed_roms.py`、`tools/add_game.py`、`add_game.ps1` | 导入检查、ROM 表生成、失败回滚；实现完成后再放行 Mapper 4 |
| `Roms/roms.json`、`User/nes/nes_roms.c` / `.h` | 菜单清单与生成数据；不要手工编辑巨大 ROM 数组 |
| `Assets/posters/posters.json`、`tools/embed_posters.py` | 可选封面映射和生成；缺封面有默认图形，无需阻塞 MMC3 |
| `Project/Fire_F407ZG.uvprojx`、`build.ps1` | Keil 工程及仅编译的发布脚本 |

### 4.1 注册与加载限制要一起改

`nes_mapper.c` 直接 `#include "mapper/xxx.cpp"`，这些是被 C 文件包含的实现片段。可以按现有方式增加 `004.cpp`、MapTab 项和 `MAP4_Init` 分支；**不要又把同一片段作为独立 C++ 源文件加入 Keil，造成重复编译或 ABI 问题**。

`Nes_Load` 不仅有 mapper 白名单，还有“非 Mapper 2/40 的 PRG 不超过 32 KiB”等限制。只加 `MapperNo==4` 仍会拒绝当前 SMB3。导入器的 `SUPPORTED` 与 `validate()` 实际白名单也是两处，须同步。

为 Mapper 4 写清支持的 PRG/CHR 大小、CHR RAM、镜像类型等范围，不要为通过当前文件而解除所有检查。当前 CHR 存储上限是 128 KiB，正好容纳本文件；暂不宣称支持所有 MMC3 的最大容量。

### 4.2 初始化顺序存在风险

当前卡带加载顺序：

```c
PPU_reset();
Mapper_Init();     // 内部会调用 mapper Reset
cpu6502_init();    // 初始化 PRG base/mask、默认映射/分发表，并复位 CPU
```

因此在 `MAP4_Reset` 中直接切 bank，可能使用尚未为新 ROM 初始化的 base/mask；随后 CPU 初始化也可能覆盖映射或 SRAM 分发表。需要保证：先准备合法的 CPU 映射基础，再安装 mapper 状态，最后按最终映射读取复位向量。可设计两阶段初始化或受控重置，具体方案由接手者验证；不要只机械调换三个函数。

FDS 已有安装专用 PRG RAM/BIOS 映射后调用 `cpu_reset_now()` 的流程。修改公共初始化后须回归 FDS 和跨游戏切换，不能破坏这条路径。`MAP1`、`MAPx` 当前只是未分配的指针；新增 MMC3 状态建议用明确的静态存储，不要直接解引用它们。

### 4.3 PRG 切换不等于只改指针

- `set_CPU_bank4..7` 对应 `$8000/$A000/$C000/$E000` 的四个 8 KiB 窗口；包装的参数类型为 `signed char`，容量边界要显式检查。
- `memmap_tbl` 对 ROM 窗口存的是偏置指针，使用“偏置 + 原始 CPU 地址”取值，不能与 SRAM 原始基址混用。
- **当前 `map89_ / mapAB_ / mapCD_ / mapEF_` 只更新映射表并返回，没有执行下面 16 KiB 映射路径的 `flush`。** 6502 的 r9 是编码后的宿主 PC，`lastbank` 也参与地址还原。必须追踪 mapper 写入返回路径，验证“正在执行的窗口被自己切换”后下一条指令来自新 bank。
- 解决方法要兼顾 ASM 内调用和从普通 C/测试直接调用的情况。不要盲目把依赖 r9 的 `flush` 插到普通 C 调用路径。
- `Nes_ApuReadDmc` 的 ROM 读取走同一映射表。DMC 读到的 PRG bank 必须和 CPU 一致。

### 4.4 CHR 必须同时更新两套视图

原始 CHR 存在 `VROM_banks=0x6C000000`，解码后的图块存在 `VROM_tiles=0x6C020000`，各预留 128 KiB。

切换 1 KiB CHR bank 时，必须同时更新 PPU 原始访问指针和解码图块指针。优先复用已同时更新两者的 `set_PPU_bank* / set_PPU_banks`，并验证 bank 掩码和 2 KiB 对齐。只让 `$2007` 读对、不让画面用的缓存切换，会出现花屏。

### 4.5 `$A001` 的 PRG RAM 保护必须落到真实访问路径

当前 `$6000–$7FFF` 由 ASM 的 `sram_R/sram_W` 处理，不经过 mapper 的 `WriteLow`。因此只实现 `WriteLow` 无法实现 RAM 禁用/写保护。若改读写分发表，需要和普通卡带、FDS 的恢复流程配套，并测试跨游戏后没有残留。

`Nes_ApuReadDmc` 对普通卡带的 `$6000–$7FFF` 目前直接访问 `NES_SRAM`。任何新增通用内存读取入口也要保持规则一致；真实 NES DMC 样本窗口在 `$8000–$FFFF`，重点验证其 PRG 切换读取，不必假设真实 DMC 会访问 `$6000`。

## 5. MMC3 IRQ 是主要难点

MMC3 的计数时钟来自经过资格过滤的 PPU A12 上升沿，不能简单等同为每帧一次或无条件每条扫描线一次。寄存器配对与计数/重载/使能行为应核对 [NESdev MMC3](https://www.nesdev.org/wiki/MMC3)；强制空白期间软件也可能通过 PPU 地址操作产生时钟，见 [Programming MMC3](https://www.nesdev.org/wiki/Programming_MMC3)。

本工程接入前的事实：

1. `MAPPER` 有 `HSync/VSync` 回调，但 `Nes_Frame` **尚未调用它们**；仅实现 MAP4_HSync 不会自动生效。
2. 当前 PPU 是扫描线渲染器，没有完整逐 dot 的 PPU 总线 A12 事件流。只监听 CPU 对 `$2007` 的读写无法覆盖背景/精灵取图。
3. 一行大致先运行 113/114 个 CPU 周期，再绘制该行。引入行级 IRQ 时要明确事件相位、预渲染行、vblank、背景/精灵图案表选择和渲染使能条件，不能直接遍历全部 262 行计数。
4. 默认 2/3 的逻辑帧不提交画面，`scanline_draw` 和 `do_scanline_and_dont_draw` 必须产生一致的 mapper 时序。否则会按显示帧率改变 IRQ，出现状态栏错位或游戏速度问题。
5. `run6502` 当前在入口检查 `cpuirqf`，进入 IRQ 后会清除此标志。MMC3 需要独立保存 pending/enable/reload/counter 状态；CPU 受理中断不等于 mapper 已被确认，未确认的请求需要正确维持。`$E000` 只应确认并禁用 MMC3 自己的请求。
6. 注意 CLI/SEI、重新使能、计数为零和重载边界，避免把电平请求错误地做成一个丢失的脉冲。若改公共 IRQ 分配，保留 FDS 行为。

接手时请明确选择并记录：是接入可验证的 A12 事件模型，还是先实现适配本扫描线内核的近似方案。允许分阶段推进，但如果近似方案只能通过 SMB3 基本流程，就如实标注兼容性边界，不能声称完整、逐周期 MMC3。MMC3 芯片修订版/衍生板存在差异，应说明选择的行为模型，而不是仅凭 iNES mapper 号推断芯片修订。

## 6. 建议实施顺序

1. 保存当前源文件和生成清单快照；先确认当前本地编译及关键回归能够执行。当前工作目录没有可依赖的 Git 提交历史，不要使用破坏性恢复命令。
2. 设计 MMC3 静态状态、PRG/CHR 映射及重置方案，先用自制小 ROM 测试切 bank，再跑商业游戏。
3. 实现寄存器地址镜像、bank select/data、PRG/CHR 两种布局、镜像控制和 RAM 保护；实现并验证 IRQ 接点。
4. 在真实 Keil ARM 内核中直接加载当前 SMB3，先观察复位、标题，再验证输入、地图、关卡与 PCM；修复明确定位的问题。
5. 内核可用后同步放行导入器 Mapper 4，更新原来“拒绝 Mapper 4”的测试，保留对其他不支持 mapper 的拒绝和回滚测试。
6. 用现有导入入口加入完整名称，保留原三项顺序。没有海报时使用既有默认封面即可，不需要为实现 MMC3 另找图片。
7. 完成本地构建、回归与预览，交付文档/报告；到此停止，不执行任何硬件步骤。

## 7. 本地命令与产物

以下命令在 `D:\Project\BA_Game` 的 PowerShell 执行。默认 `python` 当前装有 Unicorn、pyelftools、Pillow；若换环境，先检查这些依赖。无需 Nature Skills 专用运行时。

```powershell
# 当前文件只读预检查；实现前预期拒绝 Mapper 4
python .\Nes_fire_emulator\tools\embed_roms.py check .\Nes_fire_emulator\Roms\SMB3.nes

# 仅本地全量构建，建议使用独立预览版本名
.\Nes_fire_emulator\build.ps1 -Version '0.13-mmc3-preview'

# 内核验证通过并更新导入器后，再执行此步加入菜单
.\Nes_fire_emulator\add_game.ps1 -Rom 'D:\Project\BA_Game\Nes_fire_emulator\Roms\SMB3.nes' -Name 'SUPER MARIO BROS. 3'

# 加入菜单后重新构建，并执行与修改相关的测试
.\Nes_fire_emulator\build.ps1 -Version '0.13-mmc3-preview'
python .\Nes_fire_emulator\Tests\test_game_import.py
python .\Nes_fire_emulator\Tests\test_nes_arm.py
python .\Nes_fire_emulator\Tests\test_nes_games.py
python .\Nes_fire_emulator\Tests\test_fds_foundation_arm.py
python .\Nes_fire_emulator\Tests\test_smb2_disk_arm.py
python .\Nes_fire_emulator\Tests\test_nes_audio.py
python .\Nes_fire_emulator\Tests\render_menu_arm.py
```

`build.ps1` 调用本机 Keil UV4 / Arm Compiler 6.24，只构建，不下载。脚本默认版本仍是 v0.12-preview，故建议显式传新版本名。它检查全量构建 `0 errors, 0 warnings`，生成 HEX/BIN 和 `Release/manifest.json`，其中 `hardware_tested=false`。AXF 为 `Project/Output/Fire_F407ZG.axf`。

命令列表不是现成的 MMC3 验收：还需要新增 MMC3 专项测试和 SMB3 游戏流程测试。公共调度/触摸等代码若未修改，不必无意义重复硬件相关验证。

**本阶段不要运行** `flash_dap.ps1`、`tools/dap_flash.py` 或任何 `*_board.py` / SWD 自动按键、读回、复位脚本。README 内历史烧录示例不构成本次授权。

## 8. 测试基础与容易漏掉的测试改动

| 现有文件 | 可复用内容 / 注意事项 |
|---|---|
| `Tests/test_nes_arm.py` | Unicorn 执行实际 AXF，覆盖 CPU/PPU、UxROM 窗口内切换、CNROM 等；包含旧的 Mapper 4 拒绝样例，需要改为另一未支持 mapper 或不合法输入 |
| `Tests/test_nes_games.py` | 按真实菜单表启动全部游戏；mapper 允许列表须加 4；颜色数量检查只证明非纯色，不证明游戏可玩 |
| `Tests/test_game_import.py` | 现有 7 项临时目录测试；`test_mapper4_rejection_changes_nothing` 应换未支持的 mapper，并新增合法 MMC3 导入用例，保留失败不改文件的保证 |
| `Tests/test_fds_foundation_arm.py` | FDS 映射、IRQ、错误输入、切回普通卡带后的 SRAM 恢复 |
| `Tests/test_fds_drive_arm.py` | FDS 真实磁盘块读取；修改公共时序/映射时按需要补跑 |
| `Tests/test_smb2_disk_arm.py` | 实际 BIOS + SMB2，标题到 1-1、移动、B+A、PCM；已有游戏流程测试参考 |
| `Tests/test_nes_audio.py` | 实际 ARM APU、PCM、队列和 Mario 多帧回归 |
| `Tests/render_menu_arm.py` | ARM LCD 绘制捕获、边界和菜单预览；新增第 4 项后检查滚动和完整名称 |

仿真脚本会屏蔽硬件输入/LCD 端口，通过 PAD 数据和扫描线捕获验证；不要把 CPU、PPU 或 mapper 本身替换成桩后声称通过。

部分脚本在模块顶层运行测试，不能假设 `import test_nes_arm` 只是加载工具函数。复用时可整理公共 harness，但保留已有断言。现有 `call()` 辅助方法主要支持前四个寄存器参数；超过四参时应实现正确的 ARM 栈传参。

**SMB3 更大，必须重新规划测试内存**：若 ROM 放在常见 scratch `0x6C080000`，其末端为 `0x6C0E0010`，会覆盖 SMB2 脚本原用的 BIOS/PCM scratch（例如 `0x6C090000`、`0x6C0B8000`）。不能直接复制原缓冲地址。也要检查仿真 stop 指令地址 `0x080FF000` 是否与扩大的固件重叠。

### 新增 MMC3 专项验收至少覆盖

- PRG 两种模式、固定尾 bank、复位向量和当前执行窗口内切换后继续取指。
- CHR 两种布局、2 KiB 偶数对齐、1 KiB bank、原始读与解码图块指针同步；越界索引不越界访问。
- 水平/垂直镜像切换；PRG RAM 使能、禁用和写保护走真实 CPU 读写路径。
- IRQ latch/reload/enable/ack、零值边界、I 标志屏蔽后再受理、pending 持续、渲染关闭及 vblank 条件。
- 相同输入序列下，绘制/跳绘制不会改变 mapper 计数和 CPU 游戏状态；处理好所选时序模型的限制。
- 连续加载与切换 `SMB3 → SMB1 → SMB2 FDS → SMB3`，没有状态、映射、读写分发表或 IRQ 残留。

### SMB3 游戏流程验收

必须覆盖标题、Start、世界地图、进入至少一个关卡、左右移动、跳跃与 B+A；保存可解释的截图与输入/状态记录。观察状态栏/滚动分割是否稳定，不能只看标题有颜色。逐逻辑帧处理 APU/PCM，检查不是静音、异常队列溢出或明显速度变化；本地音频结果仍不能代替耳机实听验收。

## 9. 不要破坏的现有内容

- `Roms/SMB3.nes` 原始字节及上述哈希；其余用户镜像、BIOS 也保留。
- `Roms/disksys.rom` 是现用有效 BIOS；旧 `fds_bios.bin` 已损坏并被拒绝，不要替换回去。现有 FDS 不需要 MMC3 才能运行。
- `Roms/roms.json` 原三项及其顺序；完整游戏名、46 字符标题校验、失败导入回滚。
- 简洁像素菜单及封面机制、字体和 OFL 许可，不回退到旧界面。缺海报不影响接入游戏。
- 输入同按、触摸 Select、返回菜单及现有耳机链路；不要顺带重写摇杆标定。
- FDS 只读/单面、无 FDS 扩展音频等已知范围，不要扩大宣传；历史板测结果仅对应历史版本。
- `Release` 中既有 v0.10/v0.11 固件、板测报告、用户验收记录。新报告用独立名称，不能覆盖成“MMC3 已上板”。

## 10. 完成后应交付

1. MMC3 实现、必要的公共接口修正、对应测试，以及通过现有工具生成的 SMB3 菜单项。
2. 本地编译的独立预览 HEX/BIN、Flash/RAM 占用与哈希；明确未烧录、未做实机性能/耳机验收。
3. 测试命令、真实通过/失败结果、SMB3 标题/地图/关卡截图及声音检查结果，不以返回码 0 代替流程验收。
4. IRQ 时序方案、已支持的 MMC3 范围、仍未验证的后续关卡或边界，更新 `Doc/adding_games.md` 与 README 对 Mapper 4 的状态说明。
5. 列出修改文件和仍需用户实机确认的项目。**交付后等待用户决定是否上板。**

本次交接文档制作仅核对了文件和源码，没有实现 MMC3、修改 ROM 清单、重新构建或操作开发板。
