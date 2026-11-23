# NesFire 新手教程

从一块空板子到玩上游戏，按顺序做这五步：

1. **烧录固件**（下载 Release 里的 `.hex`，或自己编译）
2. **准备 SD 卡**（FAT32，根目录建 `NES`）
3. **导入 ROM**（用免安装的 `NesImportGUI.exe`）
4. **上机重建目录**（第一次开机自动扫描）
5. **开玩**（没有封面的 ROM 会自动截取开始画面当海报）

---

## 1. 你需要准备

| 物品 | 说明 |
|---|---|
| 开发板 | 野火 STM32F407ZGT6 霸天虎 V2，480×800 MCU 屏，WM8978 音频 |
| 下载器 | DAP-Link 或 ST-Link（接 SWDIO / SWCLK / GND / 3V3） |
| SD 卡 | FAT32，建议 8–32 GB；卡槽在板子上 |
| 摇杆 / 按键 | 板载摇杆 + KEY1/KEY2/SW/电容键即可；也可接扩展按键板 |
| ROM | `.nes` / `.fds` 文件，**只使用你自己合法拥有的游戏** |
| 电脑 | Windows 10/11（烧录和导入助手都在 Windows 上最方便） |

> 仓库不包含任何 ROM、FDS BIOS、封面或字模。FDS 游戏需要 `DISKSYS.ROM`；
> 自己编译并需要 FDS 支持时，请自备 `Roms/disksys.rom`。

---

## 2. 烧录固件

### 2.1 为什么 Release 里没有固件镜像

固件会内置 FDS BIOS、演示 ROM 和封面，这些内容不能公开分发。因此本仓库
**只提供源码和工具**，不提供成品 `.hex`；Release 里提供的是免 Python 的
导入助手 `NesImportGUI.exe`。请按 2.2 在本地编译固件。

### 2.2 自己编译（推荐）

1. 安装 Keil 5 和 **Arm Compiler 6.24**。
2. 打开 `Project/Fire_F407ZG.uvprojx`，全量 Build。
3. 产物在 `Project/Output/Fire_F407ZG.hex`。
4. 需要 FDS 支持时，把自己合法拥有的 `disksys.rom` 放到 `Roms/`，运行
   `python tools/embed_fds_bios.py`，再 Build。
5. 想内置回退游戏/封面时，按 `Roms/roms.json` 和
   `Assets/posters/posters.json` 的格式准备自己的文件，运行
   `python tools/embed_roms.py` / `python tools/embed_posters.py`。

构建基线：0 errors / 0 warnings，固件约 200 KB。

### 2.3 烧录到板子

**STM32CubeProgrammer**：

1. 连接 DAP-Link / ST-Link，给板子上电。
2. 选择 `Project/Output/Fire_F407ZG.hex`。
3. 起始地址保持 `0x08000000`。
4. 点 **Download**，等待完成。
5. 断电再上电。

**Keil**：打开工程后 `Flash → Download`，地址同样是 `0x08000000`。

> 也可以使用 `tools/dap_flash.py`，但它需要发布清单和 pyOCD 环境；
> 普通用户用 CubeProgrammer/Keil 更简单。

---

## 3. 准备 SD 卡

1. 用 Windows 把 SD 卡格式化为 **FAT32**。
2. 在卡根目录新建文件夹 `NES`。
3. 把 `.nes` / `.fds` 直接放进 `NES/`，或放进任意子目录。
   固件会递归扫描最多 **4 层**，例如：
   ```
   NES/
     Super Mario Bros. (World).nes
     famicom/00/Contra (USA).nes
     imports/新游戏.nes
     hacks/某改版.nes
   ```

第一次开机时，固件会自动生成 `NES/CATALOG.IDX`。之后只有在
ROM 增删时才会重建，正常开机直接读取目录，速度快很多。

> 建议先备份整张 `NES` 文件夹。去重工具会把多余文件移到卡根目录的
> `_dedup_removed_*` 里，不会直接删除。

---

## 4. 用导入助手导入 ROM

双击 Release 里的 **`NesImportGUI.exe`**。这是免安装、免 Python 的版本。
如果 Windows SmartScreen 提示“未知发布者”，点 **更多信息 → 仍要运行**。

### 4.1 扫描

1. **ROM 来源**：选电脑上放 ROM 的文件夹（会递归扫描）。
2. **SD 卡 NES 目录**：选 `X:\NES`。程序会自动探测盘符。
3. 点 **扫描**。表格会标出：
   - 橙色 = **Hack / 汉化 / 改版**
   - **封面 = 缺**：同目录没有同名 `.COV`
   - **重复 = 完全相同 / 同名**

### 4.2 导入

1. 按住 `Ctrl` / `Shift` 多选游戏。
2. 点 **导入选中**。
   - 普通 ROM 复制到 `NES/imports/`
   - Hack/汉化复制到 `NES/hacks/`
   - 同名文件不会覆盖：内容相同就跳过，不同就自动加 `(2)`、`(3)`
3. 导入完成后选择 **是**，让程序把 `CATALOG.*` 改名为 `.OLD`。
   游戏机下次开机就会重新扫描。

### 4.3 封面

- 没有 `.COV` 不用管：游戏机第一次启动该 ROM 时，会等约 3 秒
  （FDS 约 6 秒），把开始画面自动写成海报。
- 想手动指定：进入 **封面** 页，选中游戏 → **用图片生成封面…**，
  选一张 PNG/JPG（建议 256×240 的 NES 截图）。
- 想重新自动截取：**删除封面（首玩自动截取）**。

### 4.4 维护

- **检查重复（只读）**：先看会保留/移除哪些，不会改文件。
- **执行去重…**：把多余版本移到卡根目录的 `_dedup_removed_*`。
  Hack、汉化、Beta、Proto、Demo、Bootleg、`[h]`、`hacks/` 目录
  **永远不参与**。
- **按英文名排序**：目录重建后运行，让菜单按英文标题排序。
- **填充拼音索引**：给中文标题补拼音，方便搜索。
- **重建目录**：`CATALOG.*` → `.OLD`，下次开机重扫。

---

## 5. 第一次开机

1. 插好 SD 卡，接好摇杆和按键，上电。
2. 等待 `STICK READY`。第一次扫描目录可能需要几秒到十几秒。
3. 菜单里用摇杆上下选择，**KEY2** 或 **SW** 进入游戏。
4. 如果菜单为空，显示 `NO GAMES ON SD`：
   - 确认卡根目录有 `NES/`
   - 确认文件扩展名是 `.nes` / `.fds`
   - 在导入助手里点 **重建目录**，再开机

### 操作表

| 操作 | 功能 |
|---|---|
| 摇杆 | 方向 |
| KEY2 | A（跳跃/确认） |
| KEY1 | B（加速/取消） |
| KEY1 + KEY2 | B + A |
| SW | Start（开始/暂停） |
| 板载电容键 CAP | Select；在设置页可切换横竖屏 |
| 菜单里 KEY2 / SW / 扩展 A、F | 进入所选游戏 |
| 菜单里 KEY1 / 扩展 B | 打开设置中心 |
| 菜单里 SELECT（扩展 E） | 打开 GAME INFO |
| 游戏中长按 SW 1.5 秒 | 静音并退回菜单 |

### 设置中心

- **SCREEN**：横屏/竖屏；横屏游戏保持 640×480 居中 4:3，两侧显示侧边面板。
- **AUDIO**：音量、输出（扬声器 / 耳机 / 静音）。
- **CONTROL**：按键测试。
- 设置页里按 **CAP** 可随时切换横竖屏（CONTROL 页保留原始测试）。

> 硬件 A 键必须接 **PE3**。PC6 已固定为 WM8978 的 I2S2_MCLK，
> 把按键接到 PC6 会导致耳机和扬声器同时无声。

---

## 6. 封面与海报

- 封面文件是 ROM 同目录、同名的 `<文件名>.COV`。
- 没有 `.COV` 时：
  1. 第一次进入游戏，等约 3 秒（FDS 约 6 秒）；
  2. 固件把当前开始画面写成 256×240 的 NCV1；
  3. 退回菜单后就能看到海报。
- 如果截到的是厂商 Logo / LOADING 画面：
  - 在导入助手里删除该 `.COV`，再进一次游戏；或
  - 手动用图片生成封面（建议 256×240）。
- 封面写入失败不会影响游戏，菜单会显示 `NO COVER`。

---

## 7. 存档、收藏与最近

- 电池存档：`NES/SAVES/`，双槽 + CRC 校验，退出游戏时写入。
- 收藏 / 最近记录：`NES/PREFS0.DAT`、`NES/PREFS1.DAT`。
- 去重和分桶工具会自动重映射这些路径键，收藏不会丢。
- 换卡前先关机，避免写入中断。

---

## 8. 大目录优化（可选）

如果一个目录里有上千个 ROM，FatFs 的路径查找会变慢。可以分桶：

```powershell
python tools\bucket_sd.py F:\NES\famicom --bucket-size 100 --apply
```

每个桶约 100 个 ROM + 同名封面，查找从 O(1550) 降到 O(100)。
分桶后需要让游戏机重扫目录；导入助手也可以直接使用。

---

## 9. 常见问题

**Q：开机显示 `SD INIT ERROR`？**
换一张 FAT32 卡，重新插紧；清理卡座触点；避免使用 exFAT/NTFS。

**Q：菜单里没有新导入的游戏？**
在导入助手里点“重建目录”，或把 `CATALOG.*` 改名为 `.OLD` 后重新开机。

**Q：游戏能列出但进不去，提示 MAPPER / HEADER / SIZE？**
该 ROM 的 mapper 暂不支持，或文件损坏。查看
[Mapper 支持](Doc/mapper_support.md)，并用 UART（115200 8-N-1）看详细错误。

**Q：没有声音？**
先在设置里确认输出不是 MUTE，音量不是 0；确认硬件 A 键接在 PE3，
PC6 不要接按键。耳机和扬声器都不响时，优先检查 PC6/MCLK。

**Q：FDS 游戏提示 `BAD FDS BIOS`？**
官方固件已内置 BIOS；自己编译时把 `Roms/disksys.rom` 放好并运行
`python tools/embed_fds_bios.py`。

**Q：去重后收藏丢了？**
正常情况下工具会重映射收藏/最近记录。如果仍有问题，从
`_dedup_removed_*` 里把 ROM 和 `.COV` 移回原位，再用导入助手重建目录。

**Q：排序后菜单顺序又变了？**
每次重建目录都会恢复扫描顺序，需要重新运行“按英文名排序”。

**Q：导入助手打不开 / 提示缺少 Pillow？**
用 Release 里的 `NesImportGUI.exe` 不需要 Python。源码版需要
`pip install pillow`。EXE 被 SmartScreen 拦截时选“更多信息 → 仍要运行”。

---

## 10. 合法使用

本项目只提供模拟器固件和工具，不附带任何游戏 ROM、FDS BIOS 或封面。
请只使用你自己合法拥有的游戏转储；不要分发受版权保护的内容。
