# 设置中心与掉电保存

基线日期：2026-11-23。适用于 `Project/Fire_F407ZG.uvprojx`（SD 库构建）。

本轮把原来的“库选项”页升级为层级设置中心，KEY1 一次普通按下即可进入，
因此库页面不再有长按手势。实现顺序为界面结构 → 音量 → 持久化 → 子页内容。

## 层级与入口

```
KEY1 / 扩展板 B（库里）
  SETTINGS
    ALL GAMES            → 应用筛选并返回游戏库
    LOADABLE             → 应用筛选，必要时分批预检头信息
    UNSUPPORTED          → 同上
    FAVORITES            → 同上
    RECENTLY PLAYED      → 同上
    SEARCH               → 搜索页；B 回设置首页，提交后回游戏库
    CONTROL          >   → 按键/摇杆/电容键实时测试（不载入 ROM）
    AUDIO            >   → VOLUME + OUTPUT（HEADPHONES/SPEAKER/MUTE）
    SCREEN           >   → 默认横竖屏
    FAVORITE             → 对当前选中游戏加/取消收藏
```

- 首页和子页共用一套列表手感：每次拨动只处理一次，回中稳定 60 ms 后才接受下一次。
- `A / KEY2 / SW / 扩展板 A、F` 为确认；`B / KEY1 / 扩展板 B` 为返回上一层，
  在首页返回游戏库。搜索页保留 `KEY2` 直接入口。
- `CAP` 在游戏库中保持原先的横竖屏一键切换；`SEL`（扩展板 E）打开 GAME INFO
  （详见 [游戏详情页](library_details.md)）。游戏内 `CAP` / `SELECT` 仍是 NES Select。
- `CONTROL` 子页沿用原 `NesSettings_Update` 的八键图，50 ms 刷新一次。

## 音量

- API：`NesAudio_SetVolume(uint8_t)` / `NesAudio_GetVolume()`，范围 0–100，默认 70。
- 软件增益不碰 WM8978 的固定输出增益：`gain_q8 = round(volume * 256 / 100)`，
  在 `NesAudio_Render` 里 `value = (value * gain_q8) >> 8`。
- 音量为 0 时仍执行 `apu_process`（保持模拟时间），只把 PCM 写成静音；
  与 `NES_AUDIO_OFF` 的“仍然处理 APU、但整体静音”一致。
- `NesAudio_Init` 每次复位音量到 70，随后 `NesApp_Init` 读取卡上记录覆盖。

## SETTINGS.BIN

路径：`0:/NES/SETTINGS.BIN`，固定 8 字节，小端。

| 偏移 | 长度 | 含义 |
|---|---|---|
| 0 | 1 | 版本，当前为 1 |
| 1 | 1 | 默认方向：0=竖屏 480×800，1=横屏 800×480 |
| 2 | 1 | 音量 0–100 |
| 3 | 1 | 音源 0=HEADPHONES，1=SPEAKER，2=MUTE |
| 4 | 4 | 前 4 字节的 CRC32（标准反射多项式，与 zlib.crc32 一致） |

规则：

- 长度不等于 8、版本不为 1、方向 >1、音量 >100、音源 >2 或 CRC 不符时整条记录作废，
  开机使用默认值（竖屏、音量 70、扬声器）。
- 每次在界面里改变方向、音量、音源后立即整文件重写，并同步；写失败只清除
  `settings_storage` 路径上的持久化效果，运行中的值保持不变。页面底部提示
  `SETTINGS NOT SAVED - CHECK SD`。
- 写失败可能把文件截断成 0 字节，下次开机按无效记录处理；再次成功保存即可恢复。
- 没有 SD 卡（内置库构建或卡启动失败）时不做任何设置写卡，也不显示写失败。

## 代码位置

| 文件 | 内容 |
|---|---|
| `User/nes/nes_menu.c/.h` | `NesSettings_Root/Control/Audio/Screen`、`NesSettings_Update` |
| `User/nes/nes_port.c` | `settings_poll`、`settings_persist`、`NesApp_Init` 启动应用、KEY1 进入 |
| `User/audio/bsp_nes_audio.c/.h` | 软件增益与音量 API |
| `User/nes/nes_library.c/.h` | `NesLibrary_LoadSettings/SaveSettings` |
| `Tests/render_menu_arm.py` | 竖屏整页渲染、进入/返回、音量与持久化回读 |
| `Tests/render_menu_landscape_arm.py` | 800×480 首页与三个子页 |
| `Tests/test_settings_arm.py` | SETTINGS.BIN 记录/CRC/边界与增益映射 |

## 验证命令

```powershell
# 全量编译（Keil UV4）
& "$env:LOCALAPPDATA\Keil_v5\UV4\UV4.exe" -r Project\Fire_F407ZG.uvprojx -j0 -sg -o Project\build.log

cd Tests
python render_menu_arm.py --sd
python render_menu_landscape_arm.py
python test_settings_arm.py
python test_audio_output_arm.py
python test_library_views_arm.py
```

烧录与全片回读（使用工作区 `.tools/dap` 环境和在线 CMSIS-DAP）：

```powershell
.\flash_dap.ps1
```

- 编译器：Arm Compiler 6.24，0 error / 0 warning。
- 本轮构建体积：Code 135,776；RO 57,808；RW 296；ZI 167,376 字节。
- 预览输出：`Tests/nes_output/settings_root.png`、`settings_control_idle.png`、
  `settings_audio.png`、`settings_screen_portrait.png`、`settings_landscape.png` 等。
  这些是 Unicorn 跑真实 LCD 调用得到的图，不是板上照片。

## 待上板确认

- 真实 SD 卡的写入延迟与反复改音量时的掉帧情况。
- 音量 0 / 70 / 100 的响度是否符合预期（软件增益与 codec 固定增益叠加）。
- 保存横屏后冷启动是否直接进入 800×480，CAP 临时旋转是否仍可覆盖。
- 触摸直接点选设置条目尚未实现（当前只处理按键/摇杆）。

## 2026-11-23 实机烧录与 SWD 验证

之前板子一直运行 v0.41：上一轮只构建了 v0.62-keys，没有执行下载。本轮通过
CMSIS-DAP（`FS-00000000`，SWD 100 kHz）烧录 `NesFire_v0.63-settings.hex`：

- Boot 备份：`backups/flash_20261123_164438_359290.bin`
- 编程后全片回读 195,584 字节一致，SHA-256
  `163764ed014e9cf0cfdc9aa7b9a2efa0146e4558a89b44238b11e91a40b7d5af`
- 记录：`Release/dap_download_v0.63-settings.json`
- 运行快照：`Release/board_settings_v0.63.json`

SWD 直接驱动 `nes_test_pad` 并读取真实 RAM，确认状态机：

| 操作 | 结果 |
|---|---|
| 上电 | `app_state=0`，`settings_page=0`，音量 70 / 增益 179，SD 1557 项 |
| 按 KEY1 等价 | `app_state=2`，设置首页 |
| 光标移到 AUDIO 后按 A | `settings_page=2`（AUDIO 子页） |
| SCREEN 子页按 A | `nes_screen_landscape` 1→0，`settings_save_failed=0` |
| 两次返回 | `settings_page=0` → `app_state=0`，回到游戏库 |

板上 `nes_faults=0`、`nes_audio_codec_error=0`、`nes_audio_dma_errors=0`、
`sd_last_error=0`、`sd_write_retries=0`；两次方向切换各写入 512 字节设置扇区。
测试结束时恢复竖屏、音量 70、扬声器，并停留在游戏库。
