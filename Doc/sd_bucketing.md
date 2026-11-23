# SD 目录分桶与封面来源

基线日期：2026-11-23。适用于 `NesFire_v0.65-details` 及之后的 SD 库固件。

## 现象

前 7 个游戏在根目录 `NES/`，选中、封面和启动都是毫秒级；`NES/famicom/` 里的
1550 个下载游戏，封面要等 1 秒以上，越靠后的游戏启动越慢。ROM 大小不是主因：
`Super Mario Bros.` 和 `1942` 都是 40,976 字节，前者的封面/ROM 打开约 1 ms，
后者的 `.COV` 打开约 1.25 s。

## 原因

FatFs 的 `f_open` 是按路径**从目录第一项开始线性扫描**，没有名称索引。目录里的
每一项占 32 字节，长文件名还会额外占 2–4 个 LFN 项。

卡上的实际结构：

| 目录 | 项数 | 内容 |
|---|---|---|
| `NES/` | 28 | 7 个 ROM + 7 个 `.COV` + 目录/字模/存档等 |
| `NES/famicom/` | **3100** | 1550 个 ROM + 1550 个 `.COV`，长中文名 |

上一轮是先把 1550 个 ROM 拷完，再批量生成 1550 个 `.COV`，FAT 目录项按创建顺序
排列，所以**所有封面都在 1550 个 ROM 之后**。于是任意一个 famicom 封面都要先扫过
约 1550 个 ROM 项；越靠后的 ROM 启动也要扫到它自己的位置。

SWD 实测（扣掉约 128 ms 的调试调用固定开销）：

| 路径 | 目录扫描量 | 实际耗时 |
|---|---|---|
| `NES/Super Mario Bros. (World).nes` | 28 项 | ~1 ms |
| `famicom/1942...nes`（目录最前） | 少量 | ~6 ms |
| `famicom/1942...COV`（所有 ROM 之后） | ~1550 项 | **~1.25 s** |
| `famicom/` 最后一个 ROM | ~1550 项 | **~2.5 s** |

（最后一次测到的末位 `.COV` 只有 ~0.14 s，是上一次扫描把目录扇区留在 SD 卡缓存里；
冷访问仍会到秒级。）

## 封面是怎么来的

- **前 7 个**：`Assets/posters` 的原生标题截图，256×240、16 色、4bpp，
  每张 30,776 字节；由 `tools/prepare_sd.py` 的 `encode_cover` 打包。
- **其余 1550 个**：上一轮从 `D:\BaiduNetdiskDownload\famicom\.previews\<ROM 同名>.png`
  批量生成：
  1. 640×480 RGBA 预览截图；
  2. 平铺到黑底；
  3. LANCZOS 缩到 228×180；
  4. 量化成 16 色；
  5. `encode_cover_image` 打包成 NCV1 4bpp。
  平均 20.1 KiB/张，共 1549 张；1 个没有预览图的用文字封面补上。
- `downloaded_images/covers` 里的 497×680 盒绘**没有使用**：它是竖版盒绘，
  而 `.previews` 是真正的游戏标题/截图，比例更接近菜单的 456×360 显示区。
- `.COV` 格式（NCV1）：24 字节头 + 16/256 色调色板 + 4/8bpp 像素；
  固件按 ROM 同路径的 `.COV` 查找。

## 分桶工具

`tools/bucket_sd.py` 把平铺目录按每组 N 个 ROM 分成数字子目录，并把同名的
`.COV` 一起移动。**ROM 和 `.COV` 交错移动**，所以桶内封面也紧挨着自己的 ROM。
每组 100 个时，每次打开最多扫约 200 个目录项。

```powershell
# 默认 dry-run，只打印计划
python tools\bucket_sd.py F:\NES\famicom --bucket-size 100

# 确认后执行
python tools\bucket_sd.py F:\NES\famicom --bucket-size 100 --apply
```

工具会：

- 校验源目录只有顶层 ROM，且还没有数字桶目录（避免重复分桶）；
- 按文件名排序，每 100 个一组建立 `00`、`01`……；ROM 与同名 `.COV` 成对移动；
- 预检查所有目标路径，冲突时不移动任何文件；
- 重映射 `PREFS0.DAT`/`PREFS1.DAT` 里的收藏/最近记录（它们按 ROM 相对路径的
  FNV-1a 64 位键保存；移动后路径变化，不重映射就会“收藏失效”）；
- 把 `CATALOG.IDX`、`CATALOG.NEW`、`CATALOG.BAK` 改名为 `.OLD`，让固件在下次
  开机时重建目录表（`.OLD` 不会被扫描）。

离线测试：`python Tests/test_bucket_sd.py`，覆盖分桶移动、封面配对、收藏/最近
键重映射和目录缓存重置。

## 在实卡上的步骤

1. 断电，取出卡，插到电脑读卡器（下例为 `F:`）。
2. 先 dry-run，确认 `roms: 1550  covers matched: 1550  buckets: 16 x <= 100`，
   并检查 `favorites/recent keys to remap` 的数量。
3. 加 `--apply` 执行；工具只做 FAT 重命名，不重写 ROM 内容。
4. 卡插回板子，开机一次，等待目录表重建（约 3 秒；`nes_library_boot_ms` 可在
   SWD/串口看到）。
5. 选中靠后的 famicom 游戏，封面和启动应降到约 0.1–0.3 秒（取决于桶大小）。
6. 确认无误后，可删除根目录的 `CATALOG.IDX.OLD`/`.BAK.OLD`。

## 注意

- **拼音搜索**：分桶会重置 `CATALOG.IDX`，固件重建时 `pinyin` 字段为空。中文/英文
  标题仍来自文件名，搜索可用；若需要拼音，开机重建后再把卡接电脑运行
  `python tools\make_pinyin.py F:\NES\CATALOG.IDX`。
- **兼容性缓存**：`COMPAT.IDX` 绑定旧的目录快照，分桶后会被忽略/重新检查。
- **存档**：`NES/SAVES/*.SV0/SV1` 按 ROM CRC 和大小命名，不受路径影响。
- **前 7 个游戏**：仍在 `NES/` 根目录，封面和名字不变，不需要移动。
- **固件**：不需要重新编译或烧录；目录扫描支持 `NES/famicom/00/...` 这种深度。
- 桶大小可按需调整：`--bucket-size 50` 更快（最多约 100 项目录扫描），
  桶数更多；`100` 是速度与目录数量的折中。
