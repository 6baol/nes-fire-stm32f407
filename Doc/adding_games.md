# 添加游戏（只导入/本地编译，不自动烧录）

v0.19：游戏库现为七款，新增恶魔城 III（USA）和 Just Breed（Japan）。支持受限 Mapper 5；MMC5 每镜像上限 896 KiB，其他 Mapper 仍为 640 KiB，受容量和板型校验共同限制。MMC5 的 SD 包要求 v0.19 固件，旧版会拒绝新索引。完整范围见 [MMC5 说明](mmc5_v0.19.md)。下文的五款列表、640 KiB 及 Mapper 清单为此前版本记录。

**v0.17 默认使用 SD 游戏库。** 当前每库最多 64 项，每个镜像最多 640 KiB，库的总大小不再受内部 Flash 的 768 KiB 预算限制。导入后运行 `build.ps1` 会自动生成本机 `Release/SD_ROOT/NES`；也可单独运行 `python tools/prepare_sd.py`。确认读卡器盘符后用 `python tools/install_sd.py F:/ --update-index` 安装新增资源并明确允许更新固件索引；脚本不会格式化、删除文件或覆盖不同内容的 ROM/封面，也不会操作卡上的 TH06。`--update-index` 只允许更新 LIBRARY.IDX 与 SD17.JSON 两个生成的元数据文件。完整步骤见 [SD_card_v0.17.md](SD_card_v0.17.md)。下文旧的总镜像 768 KiB 限制仅适用于可选 `build.ps1 -Embedded` 全内置版本。

当前游戏列表为五款：三款 Mario、Metroid、Wizards & Warriors。Controller Test 为菜单 KEY1 打开的原生 Settings 输入检查页，不作为 ROM 条目。开发用 controller_test.nes 文件保留，但不嵌入固件。

在 `D:\Project\BA_Game` 打开 PowerShell。

## 一条命令

```powershell
.\Nes_fire_emulator\add_game.ps1 -Rom 'D:\Games\game.nes' -Name 'FULL GAME NAME' -Build
```

`.fds` 用同样的命令。会检查格式和当前实现的 Mapper，将文件复制到 Roms，添加或更新菜单并生成 ROM 数据；加 `-Build` 继续调用 Keil 编译，不加则只导入。既有游戏保持原位置，新游戏追加到末尾。名称支持最多 46 个可打印英文字符（显示为大写），菜单按单词换行，不截成缩写。中文文件路径可以使用，屏幕标题暂用英文。

## 同时添加海报

```powershell
.\Nes_fire_emulator\add_game.ps1 -Rom 'D:\Games\game.fds' -Name 'FULL GAME NAME' -Cover 'D:\Games\cover.jpg' -Build
```

PNG/JPG 均可，建议竖版 2:3。图片自动复制到 Assets/posters，配置映射并生成 240x360 的索引色数据；不提供图片时使用默认图形。替换海报时再次运行同一条命令即可，不会复制出第二条游戏。更换封面不会修改原始图片。

## 检查、查看、移除

```powershell
python .\Nes_fire_emulator\tools\embed_roms.py check 'D:\Games\game.nes'
python .\Nes_fire_emulator\tools\embed_roms.py list
python .\Nes_fire_emulator\tools\embed_roms.py remove game.nes
```

`check` 只读，不改菜单。失败的导入会保留原列表及生成源文件；封面生成失败也会回滚本次导入。移除只从列表中删除，不删除 Roms 中的原文件。导入通过表示格式与已实现 Mapper 匹配，仍需仿真/实机兼容性测试。

## 当前限制

- 当前可导入卡带 Mapper 0、1、2、3、4、7、11、66、71。新增 11/66/71 只有自制 ROM / 内存 FAT32 本地 ARM 验证，待对应游戏逐款验收；容量和板型限制见 [mapper_support.md](mapper_support.md)。基础 MMC1B 与 AxROM 已使用 Metroid / Wizards & Warriors 验证。默认 SD 版本为带 battery 标志的 8 KiB 卡带 SRAM 提供双槽持久化，见 [存档说明](saves_fds_v0.17.5.md)；新写卡功能仍需实机验收。

- Mapper 40 是继承的实验实现，兼容性未验收。Mapper 4 要求 32～256 KiB PRG，CHR 为不超过 128 KiB 的 2 次幂，CHR=0 时使用 8 KiB CHR RAM。
- MMC3 支持 PRG/CHR banking、镜像、PRG RAM 保护及 IRQ；IRQ 使用扫描线级 A12 近似，不是点级精确或全部 MMC3 修订版实现，同 Mapper 的其他游戏仍需逐个验证。
- FDS 导入目前仍限制单面、只读镜像，使用已配置的完整 BIOS。内核已有 Select+左/右手动换面（仅自制双面测试验证）及 FDS 波表/包络/调制声音；没有自动换面和写盘存档。
- 默认 SD 库每个镜像不超过 640 KiB；仅 `-Embedded` 全内置模式合计 ROM 上限 768 KiB，且还须加上海报后通过 Keil 链接预算。
- 不支持的 Mapper、坏文件、过长或不合规的屏幕标题会在修改菜单前被拒绝。

`Roms/SMB3.nes` 为列表第 3 项 `SUPER MARIO BROS. 3`（从 1 起计），已配置游戏标题画面封面。原始 393,232 字节文件及其 SHA-256 保持不变。本地 ARM 回归覆盖标题、地图、关卡 1-1、移动、跳跃和非静音 PCM；各历史版本的板上验收见 README。

本轮只离线开发。上述导入脚本不调用下载器；默认运行方式需要已有 SD 卡及匹配的 NES 目录。`build.ps1` 只在电脑上生成资源目录，物理写卡须另行执行安装步骤。
