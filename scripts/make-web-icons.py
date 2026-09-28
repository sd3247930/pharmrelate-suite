#!/usr/bin/env python
"""从桌面端品牌图标生成手机分发站（web/icons）需要的 PNG 资源。

用法（在仓库根目录执行）：

    python scripts/make-web-icons.py

产物：

    web/icons/icon-192.png           PWA 图标（任意用途，保留透明）
    web/icons/icon-512.png           PWA 图标（任意用途，保留透明）
    web/icons/icon-512-maskable.png  PWA 蒙版图标（铺满品牌色底，留安全边距）
    web/icons/og-cover.png           微信 / QQ 分享预览图（1200×630）

图标源与 Windows 安装包同源（desktop/src-tauri/icons/icon.png），
保证手机端与桌面端看起来是同一个产品。
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
SOURCE = ROOT / "desktop" / "src-tauri" / "icons" / "icon.png"
OUT_DIR = ROOT / "web" / "icons"

BRAND = (15, 122, 140, 255)      # #0f7a8c，与 web/styles.css 的 --primary 同源
BRAND_DARK = (11, 98, 116, 255)  # #0b6274
ACCENT = (255, 194, 46, 255)     # #ffc22e

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
    if not SOURCE.exists():
        raise SystemExit(f"找不到图标源：{SOURCE}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    source = Image.open(SOURCE).convert("RGBA")

    # 1) 普通图标：等比缩放，保留透明通道
    for size in (192, 512):
        icon = source.resize((size, size), Image.LANCZOS)
        icon.save(OUT_DIR / f"icon-{size}.png", "PNG", optimize=True)
        print(f"已生成 web/icons/icon-{size}.png")

    # 2) 蒙版图标：铺满品牌色底 + 78% 居中图形，被圆形 / 方形裁切时不掉内容
    maskable = Image.new("RGBA", (512, 512), BRAND)
    inner = int(512 * 0.78)
    maskable.alpha_composite(
        source.resize((inner, inner), Image.LANCZOS),
        ((512 - inner) // 2, (512 - inner) // 2),
    )
    maskable.save(OUT_DIR / "icon-512-maskable.png", "PNG", optimize=True)
    print("已生成 web/icons/icon-512-maskable.png")

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
    draw.text((430, 460), "点右上角「📲 安装」下载 APK", font=sub_font, fill=ACCENT)
    cover.save(OUT_DIR / "og-cover.png", "PNG", optimize=True)
    print("已生成 web/icons/og-cover.png")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
