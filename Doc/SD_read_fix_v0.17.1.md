# SD 识别/读取修复（v0.17.1，2026-11-18）

## 板上原始证据

用户报告插卡后仍提示无卡。仅以 attach 模式读取正在运行的 v0.17，没有 halt/reset/烧录：`sd_initialised=1`、`sd_active=1`、索引 5 项、主循环仍运行、SysTick 正常、CFSR/HFSR 为 0；HAL SD ErrorCode=`0x20`（RX FIFO overrun），SDIO 时钟 16 MHz、4 位总线。记录在 `Release/sd_v0.17_rx_overrun.json`。

因此不能把提示等同于物理未插卡：v0.17 将初始化/4 位切换失败都写成 NO SD；现场还证明存在后续读取溢出。轮询读卡的高输入速率、外扩 SRAM 目的缓冲及 DMA 音频中断延迟可能共同导致 FIFO 来不及取空；尚不把任一因素单独认定为唯一原因。

## 修复

- 默认轮询时钟 16 MHz 降到 1 MHz / 4 位。初始化或总线设置失败时重新初始化，回退 400 kHz / 1 位，最多三次。
- 每次只读一个 512 字节扇区到 4 字节对齐的内部 SRAM 缓冲；传输完成后再复制到目标，兼容 FatFs 的不对齐目的缓冲并避免 FIFO 直接写 FSMC。
- 失败时记录错误、Abort/停止数据通路、清标志，每扇区最多两次。没有关中断，也没有写 SD 文件。
- 区分 SD INIT/BUS ERROR（带 HAL 错误码）、挂载读错和 FAT 格式错；不再将初始化失败直接判定为没有卡。
- 增加 sd_last_error / sd_init_attempts / sd_read_retries / sd_blocks_read / sd_bus_width 只读诊断量。

## 本地验证

Keil 全量构建零错误/零警告。`Tests/test_sdio_polling_arm.py` 运行真实 ARM SDIO 包装代码，模拟 HAL 指令返回，覆盖默认/回退时钟及总线、内部对齐中转、RX 溢出恢复、重试上限和扇区边界。FatFs、五款 ROM/封面、损坏输入、菜单与 Settings 回归通过。模拟不验证物理 SDIO 电气时序。

固件：`Release/NesFire_v0.17.1-sd-preview.hex` / `.bin`。用户随后明确允许下板。v0.17.1 烧录并完整读回一致，但上电电压协商未就绪，三次初始化均报 `0x01000000`（INVALID_VOLTRANGE），因此没有通过实机验收。

## v0.17.2 补充修正与实机验证

固定 3.3V 主机不请求 1.8V 切换；ACMD41 改为完整电压窗口与高容量能力，卡未就绪时每次等待 1 ms，每次初始化最多约 1.5 s，避免旧 HAL 的 65535 次长循环。未将 MCU 复位等同于 SD 供电重启。

2026-11-18 烧录 `NesFire_v0.17.2-sd-preview`，受影响 Flash 扇区备份到 `../backups/flash_20261118_174339.bin`，138240 字节完整读回与 BIN 一致。一次初始化成功，4 位/1 MHz，总目录五项、封面循环全部通过。SMB3 的 393232 字节从卡载入 SRAM 后与原始 ROM 逐字节一致，逻辑 61 Hz、画面 20 Hz；读卡错误/重试、CPU/硬件异常、音频 DMA 错误、APU 丢弃及逻辑丢帧均为 0，游戏运行期间扇区读取计数不增加。

报告：`Release/dap_download_v0.17.2-sd-preview.json` 与 `Release/board_sd_v0.17.2-sd-preview.json`。测试全程不写 SD 文件，不在 SDIO 传输中 halt；仅 SWD 注入测试按键，结束均释放。FDS 补充测试另存 `Release/board_sd_fds_v0.17.2-sd-preview.json`，以该报告最终 result 为准。PPU 副本不是 LCD 拍照，音频计数不等同于耳机实际听感。

FDS 补测结果为 PASS：复位后再次首次初始化成功，65500 字节预载与源 FDS 完全一致，BIOS 读出磁盘后进入 1-1；右移 X 从 40 增到 118，B+A 加速跳 Y 从 176 减到 118；逻辑约 60 Hz、画面约 20 Hz，SD/CPU/音频 DMA/APU 丢弃均为 0，游戏期无物理 SD 读取。首次辅助脚本在复制 PPU 画面期间错过标题输入时机而进入演示，失败记录保留为 `Release/board_sd_fds_attempt1_timing.json`；调整脚本为标题就绪立即 Start 后通过，固件未再修改。最终留下 SMB2 运行，测试按键均释放。
