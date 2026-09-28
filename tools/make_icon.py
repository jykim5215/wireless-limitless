"""Draw the app icon (two earbuds + sound waves on a soft blue squircle).

Writes assets/icon.png (1024 px) and assets/icon.ico (16..256 px).

    .venv\\Scripts\\python.exe tools\\make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
S = 1024


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def squircle_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def draw_bud(d: ImageDraw.ImageDraw, cx: float, cy: float, flip: bool) -> None:
    head_r = 118
    stem_w, stem_h = 92, 300
    white = (255, 255, 255, 255)
    # head
    d.ellipse((cx - head_r, cy - head_r, cx + head_r, cy + head_r), fill=white)
    # stem (rounded bar) angled slightly outward
    sx = cx + (-34 if flip else 34)
    d.rounded_rectangle((sx - stem_w / 2, cy + 20, sx + stem_w / 2, cy + 20 + stem_h), radius=stem_w / 2, fill=white)
    # speaker mesh
    mesh = (10, 102, 208, 255)
    mx = cx + (40 if flip else -40)
    d.ellipse((mx - 42, cy - 52, mx + 42, cy + 32), fill=mesh)


def main() -> None:
    top, bottom = (58, 145, 245), (10, 92, 200)
    bg = Image.new("RGBA", (S, S))
    px = bg.load()
    for y in range(S):
        row = lerp(top, bottom, y / (S - 1))
        for x in range(S):
            px[x, y] = (*row, 255)
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(bg, (0, 0), squircle_mask(S, 230))

    # soft highlight in the upper-left
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-260, -320, 700, 520), fill=(255, 255, 255, 46))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    icon = Image.alpha_composite(icon, Image.composite(glow, Image.new("RGBA", (S, S)), squircle_mask(S, 230)))

    art = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(art)
    # sound waves on the outer sides of the buds (same motif as the in-app logo)
    for (cx, cy), (start, end) in (((372, 470), (148, 212)), ((652, 470), (-32, 32))):
        for radius, width, alpha in ((200, 32, 235), (272, 30, 150)):
            d.arc((cx - radius, cy - radius, cx + radius, cy + radius), start=start, end=end,
                  fill=(255, 255, 255, alpha), width=width)

    buds = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bd = ImageDraw.Draw(buds)
    draw_bud(bd, 372, 470, flip=False)
    draw_bud(bd, 652, 470, flip=True)
    left = buds.crop((0, 0, 512, S)).rotate(-9, center=(372, 470), resample=Image.BICUBIC)
    right = buds.crop((512, 0, S, S)).rotate(9, center=(140, 470), resample=Image.BICUBIC)
    rotated = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    rotated.paste(left, (0, 0), left)
    rotated.paste(right, (512, 0), right)

    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow.paste((10, 40, 90, 110), (0, 0), rotated.split()[3])
    shadow = shadow.transform(shadow.size, Image.AFFINE, (1, 0, 0, 0, 1, -18)).filter(ImageFilter.GaussianBlur(22))

    icon = Image.alpha_composite(icon, art)
    icon = Image.alpha_composite(icon, shadow)
    icon = Image.alpha_composite(icon, rotated)

    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    icon.save(out / "icon.png")
    icon.save(out / "icon.ico", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.resize((256, 256), Image.LANCZOS).save(out / "icon-256.png")
    print("wrote", out / "icon.ico")


if __name__ == "__main__":
    main()
