# 游戏库列表与 GAME INFO 详情页

基线日期：2026-11-23，固件 `NesFire_v0.64-details`。

## 动机

卡上目录标签通常是 `[中文名][地区]英文标题`（例如
`[1943-中途岛战役][日版]1943 - THE BATTLE OF VALHALLA (JAPAN)`）。旧菜单把整串
标签逐行用 24 px 中文字模绘制：

- 每个新汉字都要从 SD 卡上的 `FONT.HZK` 读取 24×24 点阵，滚动到新标题时会卡；
- 宋体 24 px 的细横/撇捺二值化后断笔，列表看起来“断续”。

现改为：**列表只显示拉丁标题**（Flash 8×8 字体，16 px），**SELECT 打开 GAME INFO**
再按需加载完整中文标签和元数据。

## 列表标签提取

`Ues/nes/nes_menu.c` 的 `ascii_label()`：

1. 跳过标签开头的所有 `[...]` 组（中文名、地区、版本都在这里）；
2. 只保留 ASCII 可见字符，跳过其余 UTF-8 字符；
3. 折叠连续空格，去掉首尾空格。

结果：

| 目录标签 | 列表显示 |
|---|---|
| `[1942][日美版]1942 (JAPAN, USA)` | `1942 (JAPAN, USA)` |
| `[1943-中途岛战役][日版]1943 - THE BATTLE OF VALHALLA (JAPAN)` | `1943 - THE BATTLE OF VALHALLA (JAPAN)` |
| `SUPER MARIO BROS. 2 (JAPAN) (EN)` | 原样 |

纯中文标签提取为空时，退回文件名的 ASCII 部分；仍为空则显示 `GAME <序号>`。
列表行使用 Flash 像素字体（16 px），不再逐行读 CJK 字模。

## SELECT 详情页

- 在游戏库中按 **扩展板 E（SELECT）** 打开 `GAME INFO`；按住只触发一次。
  **CAP 电容键保持原先的横竖屏一键切换**，不再打开详情；游戏内 CAP/SELECT 仍是 NES Select。
- SELECT 不再用于“向下移动一行”。摇杆上/下仍是移动，左右翻页。
- 详情页 `A / KEY2 / SW / 扩展板 A、F` 启动当前游戏，`B / KEY1 / 扩展板 B` 返回游戏库。
- 返回列表时会清掉菜单的按键武装（`menu_armed=0`），所以关闭详情页的同一个 B
  即使还按着，也不会紧接着打开设置中心；必须松开后再按一次才算新的 B。
- 游戏内 `SELECT` / `CAP` 保持不变，仍映射为 NES Select。

目录标签在 `NES_IMPORT_LABEL_MAX`（96 字节）处会截断。若标签正好是文件名的
前缀（例如第 158 项 `[北斗之拳4][日版]HOKUTO... (JAPAN`），列表和详情会回退到
完整文件名，补回 `(Japan)` 的右括号；自定义标签（不匹配文件名）保持原样。

详情页字段（有则显示）：

| 字段 | 来源 |
|---|---|
| 完整标题（UTF-8，含中文，最多 4 行竖屏 / 3 行横屏） | `NesLibrary_Game()->label` |
| `INDEX n/count` | 当前视图序号和条目数 |
| `SIZE nK` | 目录记录中的文件大小 |
| `MAPPER n` | 头信息预检结果 |
| `HEADER OK` / 预检原因 | `NesLibrary_Compatibility(index, 1, ...)` |
| `FAVORITE` | `NesLibrary_IsFavorite()` |
| `FDS DISK` | 扩展名 `.fds` 或 mapper 20 |

当前目录没有独立的简介、年份或平台字段，所以详情页不显示这些；将来若在
`CATALOG.IDX`/`TITLES.DB` 增加对应字段，可在这里追加。

## 代码位置

| 文件 | 内容 |
|---|---|
| `User/nes/nes_menu.c/.h` | `ascii_label`、列表行 16 px 绘制、`NesDetails_Draw` |
| `User/nes/nes_port.c` | `APP_DETAILS`、`open_details`、`details_poll`、SELECT 边沿检测 |
| `Tests/render_menu_arm.py` | 电容键打开详情、B 返回、竖屏截图 |
| `Tests/render_menu_landscape_arm.py` | 横屏详情页边界检查 |
| `Tests/test_cjk_lcd_arm.py` | 24 px 中文字模逐像素验证 |

## 验证

- 离线：`python Tests/render_menu_arm.py --sd`、
  `python Tests/render_menu_landscape_arm.py`、`python Tests/test_cjk_lcd_arm.py`
  全部 PASS；所有 LCD 矩形/像素流边界检查通过。
- 实机：`NesFire_v0.67-title` 已通过 CMSIS-DAP 烧录并完成 197,632 字节全片回读。
  SWD 读取板上状态：`app_state=7`（GAME INFO），`CjkFont_Cell()=24`；
  第 158 项的详情页用完整文件名显示 `...(Japan)`，CAP 按键恢复菜单横竖屏切换。
- 记录：`Release/dap_download_v0.67-title.json`、`Release/dap_download_v0.65-details.json`。

## 已知限制

- 中文字模仍只覆盖 GB2312；GB2312 之外的字符显示为 `?`。
- 详情页不显示完整文件路径；列表的英文标题过长时在横屏只显示一行，完整标题在详情页。
- `FAVORITE` 是当前视图的收藏状态；收藏列表本身仍由设置中心的 FAVORITE 项管理。
