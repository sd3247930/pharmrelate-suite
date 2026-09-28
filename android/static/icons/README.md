# Android 启动图标

- `pharmrelate-foreground-source.png`：内置 `imagegen` 基于上传图片生成的透明前景源图。
- `pharmrelate-round-imagegen-source.png`：根据已发布 APK 与品牌图形生成的圆形 Logo 设计稿。
- `app-icon-round-master-1024.png`：严格两色、透明圆外区域的圆形母版。
- `app-icon-round-*-*.png`：`manifest.json` 实际引用的 HBuilderX Android 云打包图标。
- `app-icon-round-foreground-1024.png`、`app-icon-round-background-1024.png`、`app-icon-round-monochrome-1024.png`：圆形方案的前景、背景与单色层。
- `app-icon-round-mask-preview.png`：圆形、方圆、圆角矩形三种启动器遮罩预览。
- Web 分发站以 `app-icon-round-master-1024.png` 和前景层为唯一图标源，由
  `scripts/make-web-icons.py` 生成带版本号的 favicon、PWA 与分享预览资源。
- 仓库只发布当前 `round` 方案；`manifest.json` 不引用任何旧版图标。

重新生成：

```powershell
python scripts\make-android-icons.py
```

配色来自 Android 工程主题：主色 `#0E6E7A`，前景 `#E4F1F3`。关键图形被限制在 66/108 Android 安全区内。

HBuilderX 标准运行基座使用 DCloud 自带图标；本图标在自定义基座或云打包 APK 中生效。
