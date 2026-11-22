# NES Fire Emulator v0.5

运行平台：野火 STM32F407ZGT6 霸天虎 V2、480×800 MCU 电容屏、HW-504 摇杆、板载 1 MB SRAM。原 Bullet garden 工程没有修改。

已实现首版 NES 模拟器：6502 汇编内核、逐扫描线 PPU、iNES ROM 检查与内置加载、Mapper 0（NROM）/2（UxROM）/3（CNROM）、CHR RAM、单人手柄输入。256×240 画面等比例放大为 480×450，保留全部画面。逻辑目标 60 Hz，隔帧显示目标 30 Hz，实际速度须上板测量。

**暂时不需要 SD 卡。** ROM 编入 STM32 内部 Flash；更换游戏需要重新编译、烧录。当前发布固件内置用户放入的 `Roms/smb.nes`（Super Mario Bros）；`Roms/controller_test.nes` 仍保留为自行编写的回归测试卡带。要直接在卡上放多个游戏、浏览和切换游戏，后续可以加入 SDIO + FAT 文件系统；该功能当前没有实现。

## 烧录与操作

烧录 `Release/NesFire_v0.5.hex`。Keil 工程仍为 `Project/Fire_F407ZG.uvprojx`。使用 BIN 时起始地址为 `0x08000000`。v0.1 已于 2026-11-16 按用户要求通过 Fire CMSIS-DAP 下载 Mario 固件，并逐字节读回校验全部 90,112 字节；v0.2 的下载结果以 `Release/dap_download_v0.2.json` 为准。

```powershell
# 从 BA_Game 目录执行
.\Nes_fire_emulator\build.ps1
.\Nes_fire_emulator\flash_dap.ps1
# 只核对已烧录内容
.\Nes_fire_emulator\flash_dap.ps1 -VerifyOnly
```

DAP 脚本沿用工作区 `.tools/dap` 环境，检查发布哈希，备份所有将受影响的完整 Flash 扇区，按扇区写入，然后逐字节读回。禁止自动解锁。新脚本按 STM32F407 的 16/64/128 KiB 扇区划分计算备份范围，支持大于 64 KiB 的固件。没有连接下载器时会报错退出。

接线沿用已经调通的小游戏：VRx→PA4（CN3-25）、VRy→PA6（CN3-21）、SW→PB7（CN3-23）、电源→3V3、GND→GND；摄像头接口保持空置。上电释放摇杆，等待屏幕底部 `STICK READY`。

| 控制 | NES 按键 |
|---|---|
| 摇杆 | 上下左右，支持斜向 |
| KEY2 | A |
| KEY1 | B |
| 摇杆按下 SW | Start |
| 板载电容按键（PA5） | Select |
| 同时按 KEY1 和 KEY2 | B+A，可按住加速再跳跃；Select 使用板载电容按键 |
| 触摸底部左/右区域 | Select / Start，坐标尚待实机确认 |

测试 ROM 中左右/上下移动小精灵，按 A 改变小精灵颜色。该测试 ROM 不为 B/Start/Select 设置游戏行为。实体按键可绕开未验收的触摸坐标。

## 换成自己的 ROM

使用有权使用的 `.nes` 文件：

```powershell
python .\Nes_fire_emulator\tools\embed_rom.py 'D:\你的目录\游戏.nes'
.\Nes_fire_emulator\build.ps1
.\Nes_fire_emulator\flash_dap.ps1
```

转换工具会在修改嵌入数据之前检查 ROM；不支持的 Mapper 会明确报错。当前条件：NTSC、旧版 iNES、PRG 为 2 的幂；Mapper 0 为 16/32 KiB PRG 和 0/8 KiB CHR；Mapper 2 为最大 512 KiB PRG 和 CHR RAM；Mapper 3 为 16/32 KiB PRG 和最大 128 KiB CHR。Trainer、带电池标记、四屏镜像、PAL、VS、PlayChoice 均拒绝加载。嵌入工具可将无额外 RAM、无子 Mapper、标准控制器、NTSC/多区域的普通 NROM CHR-ROM NES 2.0 头转换为兼容 iNES 头；运行时仍使用 iNES。原文件不改动，PRG/CHR 数据逐字节保持不变，源文件和嵌入文件分别记录哈希。其他 NES 2.0 配置仍拒绝。格式依据：[NESdev NES 2.0](https://www.nesdev.org/wiki/NES_2.0)。ROM 信息与哈希保存在 `Roms/current.json`。

恢复自制 ROM：

```powershell
python .\Nes_fire_emulator\tools\make_test_rom.py
python .\Nes_fire_emulator\tools\embed_rom.py .\Nes_fire_emulator\Roms\controller_test.nes
.\Nes_fire_emulator\build.ps1
```

## 验证范围与限制

Keil Arm Compiler 6.24 全量构建：0 errors、0 warnings，当前 Mario 发布 BIN 为 90,112 字节、约 23 KiB 片内 RW/ZI；CHR 原始数据与预解码缓存使用外部 SRAM 共 256 KiB。启动 SRAM 自检失败时停止运行并显示错误。

`Tests/test_nes_arm.py` 使用 Unicorn 执行本次 Keil 生成的真实 ARM AXF，检查 CPU 复位/NMI、自制 ROM 画面、左右输入、A 键、跳帧、异常 ROM、CHR ROM 写保护、UxROM 执行区换页、CHR RAM 更新、CNROM 换页和调色板镜像。运行：

```powershell
python -m pip install unicorn pyelftools
python .\Nes_fire_emulator\Tests\test_nes_arm.py
```

结果在 `Tests/nes_output/results.json`；`controller_test.ppm/png` 是仿真 PPU 输出，**不是实机截图**。芯片指令仿真没有模拟 FSMC/LCD/ADC 速度，也不能证明所有同 Mapper 游戏兼容。串口为 115200、8N1，输出 logic/draw/faults/pad/ADC/ready。

本版没有声音合成、APU 帧 IRQ、DMC、存档、双人、游戏菜单和运行中换 ROM。CPU/PPU 是参考工程的近似时序内核，非逐周期精确实现；依赖 APU IRQ、特殊时序、总线冲突或未实现特性的游戏可能异常。已通过 SWD 检查板上标题、World 1-1、Start/Right 按键注入和移动；短窗口内逻辑约 50～54 Hz，画面提交约 25～27 Hz，尚未满速。画面抓取来自板上 PPU 的一次性 RGB565 副本，不是 LCD 拍照；实体按键手感、触摸方向、撕裂和长期运行仍待验收。详见 `Release/board_smb.json`。

## 代码与来源

- `User/nes/nes_main.*`：严格加载、静态内存、帧调度和静音 APU 接口。
- `User/nes/nes_port.*`：屏幕缩放、摇杆、按键、触摸、串口。
- `User/nes/6502.s`、`6502mac.s`、`cart.s`、`equates.s`、`nes_ppu.*`、`nes_mapper.*`、`mapper/*`：基于用户提供的 `其余资料/nes_simulate-master.zip` 移植；保留来源注释，原始解压内容在 `Reference/nes_simulate-master`。
- 移植修正包括 C/汇编调用栈对齐、换页寄存器保护和 PC 重定位、Mapper 2 PRG 计数、Mapper 3 CHR 掩码、加载边界、CHR 写保护与调色板镜像。
- 压缩包未发现明确的顶层许可证。这里不为参考代码新增许可证，也不假定已获得公开分发授权。
- `Legacy`、`User/game`、`User/render` 和旧的主机测试是复制时保留的小游戏资料，不参与 NES 构建；其中旧的上板报告不代表 NES 已完成硬件验收。


## Mario 上板测试

`tools/check_board.py` 使用匹配当前 AXF 的符号连接板卡，复位后抓取标题，临时注入 Start、Right、A，抓取关卡与跳跃画面，最后清除注入并复位供用户操作。诊断变量 `nes_test_pad` 默认 0；`nes_capture_request` 默认 0，只有请求时才把一个原始 256×240 RGB565 帧复制到外部 SRAM `0x6C040000`。常规运行不复制该帧缓冲。

```powershell
.\.tools\dap\Scripts\python.exe .\Nes_fire_emulator\tools\check_board.py
```

PPM/PNG 是板上 PPU 图像；`board_smb.json` 记录逻辑/绘制速率、异常寄存器和图像哈希。此测试临时接管模拟手柄，不等同于实体按键验收。

补测记录：额外抓取跳跃画面时，CMSIS-DAP HID 超时。下载器仍能枚举，但不响应命令，远程复位未能确认。已完成的标题、关卡、移动截图与报告保留；跳跃未完成实机图像确认。请按板载 RESET 清除临时测试输入并启动，继续调试前重插下载器 USB。

## v0.2 按键修复

修复 v0.1 把 KEY1+KEY2 当作 Select、抑制 A/B 的冲突。KEY1（B/加速）与 KEY2（A/跳跃）现在独立发送，允许同时按下；Select 保留在触屏底部左区。更新的屏幕提示同步反映 B+A。

v0.2 新增 `Tests/test_nes_input.py`：执行真实 Keil ARM 输入轮询代码，使用 GPIO 电平和 20 ms 消抖，检查按住 B 后按下/松开 A、反向按键顺序，以及全部 A/B/Start 组合，避免再次把 B+A 错发为 Select。


## v0.3 板载电容 Select

根据 HAL 配套例程压缩包中的 `33-TIM—电容按键/User/TouchPad/bsp_touchpad.*` 接入 PA5 / TIM2_CH1；参考源文件在 `Reference/board_touchpad`。无需新增接线，PA4/PA6 摇杆与 A/B 均保留。板载电容按键现在发送 Select，触屏左区保留为备用。

每次测量先低电平放电至少 5 ms，再由 TIM2 硬件捕获上升沿；前台分阶段查询，不阻塞游戏。计数器频率为 3.5 MHz，十次读数去掉最高/最低各两次后校准，按下门限为基线+100，释放门限为基线+60，连续两次测量确认状态。启动时手指离开电容按键约半秒；上电按住会影响基线，须松开后复位。超时/溢出/异常读数会释放 Select 并计入错误。实际灵敏度仍需实物确认，检测原始值/基线/状态可通过 `Touchpad_Get()` 读取。

电容按键回归测试：`python .\Nes_fire_emulator\Tests\test_touchpad_arm.py`。该测试执行真实 ARM 驱动，以模拟的 TIM2 捕获值检查时钟分频、相邻引脚保护、校准、消抖、迟滞、组合按键、超时和溢出处理；不代替实际触摸灵敏度验收。结果保存到 `Tests/nes_output/touchpad_results.json`。

v0.3 最新下载状态：用户排除其他工程的下载器冲突后，使用兼容本机 pyOCD 的复位枚举及单缓冲写入重新下载，91,136 字节全量读回一致，已复位启动。报告为 `Release/dap_download_v0.3.json`。板上电容按键校准就绪（空载基线 306、一次原始值 304），模拟器错误计数与 CFSR/HFSR 为 0；短窗口逻辑约 48 Hz、画面提交约 24 Hz。采样异常计数保存在 `Release/board_touchpad_v0.3.json`，实际手指触摸的 Select 响应和灵敏度尚未验收。早先失败记录 `download_v0.3_unverified.json` 仅供追溯。


## v0.4 电容按键捕获修复

v0.3 的前台查询可能晚于多次充电抖动沿，CCR1 被覆盖并置 CC1OF，驱动随后清除 Select。用户实测轨迹中触摸读数有变化但重复捕获异常大量累计。v0.4 改由 TIM2 中断锁存第一次捕获，并立即关闭捕获通道和中断；在下一次测量放电期间保持关闭。输入滤波器抑制短毛刺，前台仅处理已经锁存的值，维持非阻塞调度。取消基线十倍的额外上界，使用计数超时和有效范围约束。保留连续两次确认及按下/松开迟滞。

**J78 跳帽必须接好**：2025 年 V2 原理图第 10 页显示 TPAD1 经 J78 连接 PA5，R29 为 1 MΩ 上拉。启动时手指离开电容按键，等待基线校准。屏幕底部增加 `CAP:ON/OFF`、当前原始值/基线和 `N` 按下次数；按住时 ON，释放后 OFF，N 每次有效按下增加一次。

Mario 的 Select 用于标题页选择 1/2 人，不是暂停键；暂停使用 Start（摇杆 SW）。依据：[任天堂 Super Mario Bros. 官方说明书](https://www.nintendo.co.jp/clv/manuals/en/pdf/CLV-P-NAAAE_en.pdf)。

`tools/trace_touchpad.py` 以当前 AXF 和 manifest 的地址与哈希为准，在 CPU 持续运行时读取原始值、校准值、Select 位、按下/松开计数和错误计数；不注入按键。结果保存到 `Release/touchpad_trace_v0.4.json`。原 v0.3 的轨迹保留在 `Release/touchpad_trace_before.json`。


## v0.5 灵敏度与即时响应

按用户实测反馈，将按下门限从基线+100 改为基线+50，首次有效采样即发送 Select；释放门限为基线+25，连续两次低读数才确认松开，避免保持触摸时重复切换。v0.4 的空载轨迹约在基线+35 以内波动，保留门限余量。输入仍约每 10 ms 测量一次，实际游戏响应还包含游戏帧调度。

CAP 状态和 N 次数在状态变化时立即刷新，原始值的常规显示仍按 200 ms 节流。新增回归覆盖轻触的单次采样立即触发、保持时不重复计数、空载噪声门限和释放迟滞。v0.4 实测及用户确认 CAP 可正常切换、N 增加；v0.5 用于进一步改善轻触灵敏度。

v0.5 验收：已通过 92,160 字节全量 Flash 读回，实机轨迹错误计数为 0，用户确认“现在轻触即可切换”。验收记录 `Release/touchpad_acceptance_v0.5.json`。


## 声音选择（当前保持静音）

用户目前只有板载有源蜂鸣器，已明确选择保持静音，接耳机后再做原版游戏声音。因此 v0.5 不新增蜂鸣器提示音，现有蜂鸣器仍保持关闭；WM8978 尚未接入模拟器。开发板规格书第 12、16 页说明板载蜂鸣器为有源蜂鸣器，第 22 页说明由 PG7 高电平控制。

后续接上 3.5 mm 耳机或有源音箱后，再继续 NES APU 合成与 WM8978 / I2S2 / DMA 输出。配套 HAL 音频例程已提取到 `Reference/board_audio` 供移植参考，尚未实际验证该音频链路；原版参考 APU 在 `Reference/nes_simulate-master/User/NES/nes_apu.*`。
