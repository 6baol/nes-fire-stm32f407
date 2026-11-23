# 中文字模断笔的原因与修复

基线日期：2026-11-23。

## 现象

菜单里的中文标题出现“断续”：横画、撇捺中间缺像素，部分笔画只剩孤立点。
英文/数字使用 Flash 里的 8×8 像素字体，不受影响。

## 原因

字模不是固件现场绘制的，而是构建时由 `tools/make_cjk_font.py` 从 TTF 生成、
放在卡上 `NES/FONT.MAP` + `NES/FONT.HZK` 的 24×24 1bpp 点阵。

旧资产使用 **24 px 宋体（simsun.ttc）**：

- 宋体在 24 px 下横画只有 1 px，撇捺也只有 1 px 宽；
- 生成脚本按 128/255 做二值化，覆盖率略低的像素直接丢弃；
- 再把墨迹框居中到 24×24 格子，细画正好落在像素边界之间。

结果就是笔画断裂。对 33 个常用汉字统计，旧字模有 **12 个孤立墨点**；
`勇`、`者`、`最` 等字的横/撇都能直接看到缺行。固件 `draw_cell` 只是把
字模位逐点写成前景/背景色，没有做阈值或缩放，所以不是绘制路径的问题。

## 修复

`tools/make_cjk_font.py` 改为：

- 默认字体 `C:\Windows\Fonts\simhei.ttf`（黑体，24 px 下竖/横保持 2 px）；
- 在 2× 画布上渲染后再裁剪墨迹框，避免上/下/左/右被裁掉；
- 仍然把墨迹框居中到 24×24 格子，ASCII 继续用 Flash 字体；
- 增加 `--threshold`（默认 128），必要时可微调。

重新生成后，同一组 33 个汉字的孤立墨点为 **0**，`FONT.HZK`/`FONT.MAP`
长度不变（636,192 / 29,792 字节，cell 仍为 24），固件无需重新编译。
`Tests/test_cjk_lcd_arm.py` 通过：UTF-8 文件名、FONT.MAP 查找、FONT.HZK
位与 LCD 写入逐像素一致。

新旧对比图：`Tests/nes_output/font_simhei_vs_simsun.png`
（上排旧宋体，下排新黑体，3× 放大）。

旧字模备份：`backups/font_simsun24_20261123/`。

## 重新生成

```powershell
python tools\make_cjk_font.py
python tools\prepare_sd.py
```

输出到 `Assets/fonts/cjk`，并由 `prepare_sd.py` 复制到
`Release/SD_ROOT/NES`。可指定其他字体或尺寸：

```powershell
python tools\make_cjk_font.py --font C:\Windows\Fonts\msyhbd.ttc --size 24
```

尺寸会写进 `FONT.MAP`（第 6 字节），固件按该值调整格子；当前 24 与菜单布局
（行高、列数）匹配，不建议单独改尺寸而不检查 `nes_menu.c` 的 `UiLayout`。

## 部署到卡

字模在 **SD 卡**上，不在 Flash 里，所以更新字模不需要重烧固件：

1. 断电取出卡，接到电脑读卡器；
2. 用 `Assets/fonts/cjk/FONT.MAP` 和 `FONT.HZK` 覆盖卡上 `NES/` 下的同名文件；
3. 插回卡上电。菜单首次绘制时 `CjkFont_Ready` 会重新读取 `FONT.MAP`。

注意：`tools/install_sd.py` 默认拒绝覆盖内容不同的文件，不会自动更新字模；
需要手动复制这两个文件。卡上的 ROM、封面、存档和 `PREFS*.DAT` 不受影响。

## 2026-11-23 已写入实卡

新字模已通过 CMSIS-DAP 调用板上 FatFs 写入实卡（只写 `NES/FONT.HZK` 和
`NES/FONT.MAP`，未触碰 ROM/封面/存档）：

- 先写 `FONT.NEW` / `FONT.NEWM`，逐 8 KiB 块读回校验：
  - HZK `636,192` 字节，SHA-256 `ac04bbb37a441cc7f8b991a83cc01ca8a7e30ea563214b63d2b433b4a94343a8`
  - MAP `29,792` 字节，SHA-256 `75c82f43538298f73f864f40c043bdc65de4deaa66e755f40223fa4803f487f5`
- 校验通过后才把旧文件改名为 `FONT.HZK.OLD` / `FONT.MAP.OLD`，再替换正式文件；
  旧字模仍留在卡上，可恢复。
- 写完后硬件复位，板上 `CjkFont_Cell()` 返回 24，详情页用真实目录标签
  `[1942][日美版]1942 (JAPAN, USA)` 正常打开。
