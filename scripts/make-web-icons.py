#!/usr/bin/env python
"""从 Android 圆形 Logo 母版生成手机分发站（web/icons）需要的 PNG 资源。

用法（在仓库根目录执行）：

    python scripts/make-web-icons.py

产物：

    web/icons/app-logo-round-192-v2.png           PWA 图标（任意用途，保留透明）
    web/icons/app-logo-round-512-v2.png           PWA 图标（任意用途，保留透明）
    web/icons/app-logo-round-maskable-512-v2.png  PWA 蒙版图标（铺满品牌色底）
    web/icons/og-cover-v2.png                     微信 / QQ 分享预览图（1200×630）

图标源与 HBuilderX 云打包 APK 同源，确保安装页、PWA 与 Android 应用
展示同一套圆形品牌标识。文件名包含版本号，用于绕过浏览器与主屏图标缓存。
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - 环境缺 PIL 时给出可操作提示
    print("需要 Pillow：pip install pillow", file=sys.stderr)
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent.parent
SOURCE_MASTER = ROOT / "android" / "static" / "icons" / "app-icon-round-master-1024.png"
SOURCE_FOREGROUND = ROOT / "android" / "static" / "icons" / "app-icon-round-foreground-1024.png"
OUT_DIR = ROOT / "web" / "icons"

BRAND = (14, 110, 122, 255)      # #0e6e7a，与 Android uni.scss 同源
BRAND_DARK = (10, 85, 96, 255)   # #0a5560
ACCENT = (232, 163, 61, 255)     # #e8a33d

# 中文字体候选（Windows 自带；Linux / macOS 上按顺序回退）
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]


def load_font(size: int) -> "ImageFont.FreeTypeFont":
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise SystemExit("找不到可用的中文字体，请把字体路径加进 FONT_CANDIDATES")


def main() -> int:
    for source_path in (SOURCE_MASTER, SOURCE_FOREGROUND):
        if not source_path.exists():
            raise SystemExit(f"找不到图标源：{source_path}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    source = Image.open(SOURCE_MASTER).convert("RGBA")
    foreground = Image.open(SOURCE_FOREGROUND).convert("RGBA")

    # 1) 普通图标：保留母版的圆外透明区域，适合 favicon / apple-touch / PWA any。
    for size in (192, 512):
        icon = source.resize((size, size), Image.LANCZOS)
        target = OUT_DIR / f"app-logo-round-{size}-v2.png"
        icon.save(target, "PNG", optimize=True)
        print(f"已生成 {target.relative_to(ROOT)}")

    # 2) maskable 必须是全出血底色；前景已经限制在 Android/PWA 安全区内。
    maskable = Image.new("RGBA", (512, 512), BRAND)
    maskable.alpha_composite(foreground.resize((512, 512), Image.LANCZOS))
    maskable_target = OUT_DIR / "app-logo-round-maskable-512-v2.png"
    maskable.save(maskable_target, "PNG", optimize=True)
    print(f"已生成 {maskable_target.relative_to(ROOT)}")

    # 3) 分享预览图 1200×630
    cover = Image.new("RGB", (1200, 630), BRAND)
    draw = ImageDraw.Draw(cover)
    draw.rectangle([0, 0, 1200, 8], fill=ACCENT)
    draw.ellipse([930, 60, 1160, 290], outline=BRAND_DARK, width=3)

    icon_cover = source.resize((300, 300), Image.LANCZOS)
    cover.paste(icon_cover, (72, 165), icon_cover)

    title_font = load_font(64)
    sub_font = load_font(34)
    small_font = load_font(26)

    draw.text((430, 175), "籽关通", font=title_font, fill=(255, 255, 255))
    draw.text((430, 262), "PharmRelate Multi", font=sub_font, fill=(230, 245, 248))
    draw.text((430, 320), "手机采集端 · 扫码 / 拍照 / 手输", font=small_font, fill=(210, 236, 240))
    draw.text((430, 372), "箱 → 罐 → 粒子 · 离线可用", font=small_font, fill=(210, 236, 240))
    draw.text((430, 460), "点右上角「安装」下载 APK", font=sub_font, fill=ACCENT)
    cover_target = OUT_DIR / "og-cover-v2.png"
    cover.save(cover_target, "PNG", optimize=True)
    print(f"已生成 {cover_target.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
