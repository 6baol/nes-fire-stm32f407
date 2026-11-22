# STM32F407 构建与实机验收

## 构建

Keil 工程使用 Arm Compiler 6.24、`Keil.STM32F4xx_DFP` 2.15.0 和项目目录中的 ROM、BIOS 与 SD 资源。PC 侧验证需要 Python 3.11 或更新版本。 [Arm 编译器安装说明](https://learn.arm.com/install-guides/armclang/) · [STM32F4xx Device Family Pack](https://www.keil.arm.com/packs/stm32f4xx_dfp-keil/versions/)

在工程根目录运行，可按实际安装位置填写 `-KeilExe` 和 `-PythonExe`。如果 Arm 6.24 装在 Keil 默认工具路径之外，用 `-FromElfExe` 指定对应版本的 `fromelf.exe`。

```powershell
python -m pip install -r .\tools\requirements-validation.txt
.\build.ps1 -KeilExe 'C:\Keil_v5\UV4\UV4.exe'
```

`Release/VERSION` 设定默认版本，`-Version` 可指定本次构建标签。成功重编译后保留同版 HEX、BIN、AXF 及编译器生成的 MAP。`Release/manifest.json` 指向最新完成的构建，历史版本可使用同名的 `NesFire_v<版本>.manifest.json`。清单记录 SHA-256、Git 提交、工作区是否有改动以及链接器报告的代码和 RAM 用量。烧录回读记录与实机功能记录各自保留。

## CMSIS-DAP 运行中读取

打开开发板电源后运行。只有一个 CMSIS-DAP 探针时可以省略 `--probe`。JSON 也会打印到终端，指定 `--output` 时使用新的报告文件名。可以用 `--manifest` 选择同版归档，旧版没有归档 AXF 时用 `--axf` 指定对应文件，或用 `--flash-only` 仅核对 Flash。

```powershell
python .\tools\read_sd_state.py --probe FS-00000000 --samples 10 --interval 1 --output .\Release\board_sample_01.json
```

脚本直读 SWD 内存访问端口。整个发布 BIN 的 SHA-256 一致后才会按 AXF 读取 RAM 符号。采样读取当前页面、游戏库数量、最近一次挂载/搜索/载入/保存耗时、逻辑及绘制帧率、读写重试、保存计数、音频与 CPU 异常计数。旧版没有的字段会列在 `unavailable_counters`。脚本在 DAP 握手或采样超时时退出，可用 `--timeout` 设置等待时间。

`flash_dap.ps1 -VerifyOnly` 会暂停目标。游戏中、扫描卡或写存档时使用上述 SWD 读取脚本观察运行状态。

## 多游戏帧率对照

从参考 SD 卡的完整游戏库开始，松开手柄。脚本先核对板上完整固件与清单，再检查所选文件及载入的 ROM，按模拟器逻辑帧发送固定输入，记录每款游戏约 240 个逻辑帧的首关窗口。两版均可运行相同命令，分别指定固件清单和新的输出文件。测试会启动游戏、更新最近游玩记录，在已识别的无电池卡带间复位切换。

```powershell
python .\tools\benchmark_frames_board.py --manifest .\Release\validation\0.43-render\manifest.json --probe FS-00000000 --output .\Release\validation\0.43-render\my-run.json
```

`logic_fps` 是实际执行的 NES 逻辑帧数除以板上计时窗口。 `draw_fps` 是合成画面的帧率。v0.43 另外记录 `lcd_update_fps`，只有向 LCD 写入了变化区段才计一帧。静止画面可以出现绘制计数上升、LCD 写入为零。结果同时保留角色位置、时钟丢帧、音频和 SD 错误计数，便于排除标题页、角色停滞或外设异常。

在上述命令中加入 `--stats-modes on off` 可以对照每秒一次的 USART1 状态日志。脚本为每组重新进入同一关卡，用主机单调时钟和板上 DWT 周期计数复核。关闭组只在测量窗口内推迟状态日志与每秒统计发布，采样使用累计计数器。测量结束后恢复截止时间。两组均保留 SWD 采样、音频 DMA、手柄和 LCD。

## 板载串口烧录与日志

霸天虎 V2 的「USB 转串口」接口通过 CH340 接入 USART1。用 `python -m serial.tools.list_ports -v` 确认 USB 串口号。下文用 `COM5` 举例。通过硬件跳帽让 BOOT0 接 3.3 V、BOOT1 接 GND，并按复位，进入 STM32 的系统引导程序。 [野火底板说明](https://doc.embedfire.com/stm32_products/must_read/zh/latest/doc/introduction_of_stm32/STM32/ebf_stm32f407_batianhu_v1_v2/stm32f407_batianhu_v1_v2.html) · [ST 串口引导协议](https://www.st.com/resource/en/application_note/an3155-usart-protocol-used-in-the-stm32-bootloader-stmicroelectronics.pdf)

```powershell
python .\tools\uart_flash.py --port COM5 --identify
python .\tools\uart_flash.py --port COM5 --skip-sync --program --manifest .\Release\validation\0.42-arm67-validation\manifest.json
```

`--identify` 读取芯片标识和 Flash 容量。若识别后重新按过复位，执行烧录时应省略 `--skip-sync`。烧录前脚本会检查清单并备份涉及的完整扇区。擦除限于这些扇区，镜像末尾之后的原始数据保留。脚本会逐字节验证整个受影响范围，并将 JSON 记录保存在备份旁边。

回读通过后，将 BOOT0 恢复为 GND，按复位启动应用。正常固件的 USART1 日志用 115200、8N1，包含游戏库数量、加载结果和游戏运行期间的逻辑帧率、绘制帧率及 CPU 故障计数。

```powershell
python -m serial.tools.miniterm COM5 115200 --dtr 0 --rts 0
```

## 实机验收顺序

1. 准备一张备用 FAT32 卡和带电池 RAM 的自制测试 ROM，先记录当前固件和卡中游戏数量。分别测冷启动、再次启动、无卡启动，确认卡加载失败时可进入内置游戏，状态与实际一致。
2. 用大容量卡测试翻页、中文/拼音搜索、快速切换选中项、收藏、最近记录和兼容性检查。对启动、搜索和载入各采 10 个独立样本，记录中位数与 P95，包含长路径、缺封面和无搜索结果场景。
3. 用覆盖各主要 mapper 的 ROM 验证进入游戏、方向和组合键、声音和退出。测 30 分钟连续运行，记录 `nes_logic_hz`、`nes_draw_hz` 和错误计数。帧率应在游戏中采样。重载游戏需要分别记录逻辑更新、绘制提交和可见画面手感。
4. 在备用卡上用测试 ROM 保存两次，确认 `SAVE OK` 后关机，重新上电核对最新存档。再分别准备卡空间不足或单槽损坏的测试卡，检查失败提示、重试和备用档恢复。保存验证通过后再用真实游戏尝试长流程。
5. 在实机验收记录注明固件 SHA-256、卡容量与 ROM 数、各场景结果和仍需人工观察的屏幕、输入或音频项目。使用 SWD 读回和实机体验各自对应的结果。

## 2026-11-22 本机验证情况

首次板侧检查中，Windows 和 pyOCD 都枚举到 `FS-00000000`。HID 后端等待首个 CMSIS-DAP 信息应答超时，备用 Windows HID 后端在打开设备时超时。该次检查未读到板上固件或运行计数，未暂停、复位或烧录目标。首次检查时 SD 卡连接在电脑侧，带卡启动和断电恢复需要独立的实机记录。

本机现有 Keil MDK 5.24a 的 Arm Compiler 6.7 可用于完整 ARM 验证。工程指定的独立 Arm Compiler 6.24 因当前环境缺少对应许可证而未完成正式构建。单独保存兼容性验证产物和清单，历史正式清单继续指向 v0.41-align。

通过下列命令可以复现 6.7 的隔离构建，输出由工程的源文件列表、定义、头文件路径和 STM32F407 内存范围生成。构建和转换均通过后输出 AXF、BIN、HEX、MAP 和日志。

```powershell
python .\tools\build_arm_validation.py --arm-bin 'D:\stm32\keil5\ARM\ARMCLANG\bin' --output-dir .\Release\validation\arm67_rebuild
```

候选产物放在 `Release/validation/0.42-arm67-validation`。下面只检查发布文件与清单的一致性，适合在准备连接实机之前运行。

```powershell
python .\tools\dap_flash.py --manifest .\Release\validation\0.42-arm67-validation\manifest.json --check-files
```
