# SMB3 画面修正记录（v0.13.1，本地预览）

日期：2026-11-17。未连接/操作 DAP、未烧录、未复位开发板。用户报告仿真器已连接，没有将此视为下载授权。

## 原因与修复

原 `User/nes/mapper/004.cpp` 的 `$A000` 将 0 映射为 A/A/B/B、1 映射为 A/B/A/B，与 MMC3 寄存器相反。游戏对名称表的写入因此落入错误的物理页，SMB3 底部状态栏被关卡地面图案覆盖。此寄存器的选择不能直接照搬 iNES 头部的镜像位。

现已修正为 0 → A/B/A/B，1 → A/A/B/B。没有改 ROM、游戏速度、IRQ 模型或硬件配置。MMC3 仍使用原有扫描线近似，后续游戏兼容性不因此获得完整保证。

原 `test_mirroring_control` 同样写反期望值，所以映射错误也会通过。现修正期望，并增加经 `$2006/$2007` 实际写入/读取名称表的别名测试，覆盖寄存器镜像地址及高数据位。新测试已确认能够拒绝原 v0.13 BIN。

`test_smb3_arm.py` 新增关卡底部三个道具卡槽白色边框的画面断言，防止仅以非纯色、正常 PC 和移动坐标宣布画面通过。保存画面时同步输出 PNG 和 PPM，避免旧 PNG 与新 PPM 不一致。

## 本地验证

- Keil 全量构建：0 errors / 0 warnings，Code=65072、RO-data=672992、RW-data=248、ZI-data=62400。
- MMC3 bank、CHR、真实 SRAM 访问、IRQ 与修正后的名称表测试通过。
- SMB3 原始 ROM：1335 个逻辑帧，标题、地图、1-1、右移、B+A、PCM 通过；CPU 错误与 APU 丢弃均为 0；绘制/跳绘制后的 CPU RAM、PC、MMC3 状态一致；道具卡槽边框断言通过。
- SMB3 → SMB1 → SMB2 FDS → SMB3 映射/IRQ 状态切换回归通过。
- 基础 CPU/PPU、UxROM/CNROM 与 ARM APU 回归通过。SMB2 原始磁盘/BIOS 启动、Start 进入 1-1、移动及 B+A 回归通过，PCM 范围为 17～251。

新固件：`Release/NesFire_v0.13.1-mmc3-preview.hex` / `.bin`；当前 AXF SHA-256：`e52e93c3e43cba75e1591e7b91e8813affc331d6715d9db89b20da2ee5f358a4`。

预览：`Tests/nes_output/smb3_world_map.png`、`smb3_level1_ready.png`、`smb3_run_right.png`。均为真实 ARM 模拟内核输出，不是板上照片。历史 v0.13 报告保留，当前代码与构建结果以 v0.13.1 为准。

复现：在 `D:\Project\BA_Game` 运行 `Nes_fire_emulator/build.ps1 -Version '0.13.1-mmc3-preview'`，然后运行 `Tests/test_mmc3_arm.py`、`Tests/test_smb3_arm.py` 及对应回归脚本；路径均相对于工程根目录。不要运行烧录或板测脚本。
