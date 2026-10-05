"""Generate the repo README banner: a navy->teal gradient with the SENDPP wordmark,
matching the XENOKING brand (same diagonal gradient family, same orange accent)."""
import math
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 300
NAVY = (10, 14, 26)
TEAL = (13, 110, 112)
ACCENT = (243, 139, 26)  # #F38B1A, sendpp's existing brand orange, shared with XENOKING

img = Image.new("RGB", (W, H))
px = img.load()
# Diagonal gradient navy (top-left) -> teal (bottom-right)
diag_max = W + H
for y in range(H):
    for x in range(0, W, 2):  # step 2, mirror next pixel — cheap 2x speedup, imperceptible
        t = (x + y) / diag_max
        t = t ** 0.85
        r = int(NAVY[0] + (TEAL[0] - NAVY[0]) * t)
        g = int(NAVY[1] + (TEAL[1] - NAVY[1]) * t)
        b = int(NAVY[2] + (TEAL[2] - NAVY[2]) * t)
        px[x, y] = (r, g, b)
        if x + 1 < W:
            px[x + 1, y] = (r, g, b)

draw = ImageDraw.Draw(img, "RGBA")

# Subtle radial glow behind the title (soft orange, low alpha) for depth
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
cx, cy, r = 190, 150, 260
for i in range(r, 0, -4):
    a = int(26 * (1 - i / r))
    gd.ellipse([cx - i, cy - i, cx + i, cy + i], fill=(*ACCENT, a))
img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
draw = ImageDraw.Draw(img, "RGBA")

title_font = ImageFont.truetype("C:/Windows/Fonts/seguibl.ttf", 78)
sub_font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 28)
tag_font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 22)

# Title with a soft drop shadow
draw.text((66, 86), "XENOSEND", font=title_font, fill=(0, 0, 0, 90))
draw.text((62, 82), "XENOSEND", font=title_font, fill=(245, 248, 252, 255))
# orange accent bar under the wordmark, echoing the lightning-bolt accent motif
draw.rounded_rectangle([64, 178, 420, 186], radius=4, fill=(*ACCENT, 255))

draw.text((64, 200), "PS5 PKG / Payload / Trainer companion", font=sub_font, fill=(235, 240, 248, 255))
draw.text((64, 238), "Rebuilt and extended — by XENOKING",
          font=tag_font, fill=(190, 205, 220, 255))

# Right-aligned small badge-style pills (static art, not live badges — those come from shields.io in the README)
pill_font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 22)
labels = ["8 LANGUAGES", "TRAINERS", "OPEN SOURCE"]
px_x = W - 40
for label in reversed(labels):
    tw = draw.textlength(label, font=pill_font)
    pad = 16
    x0 = px_x - tw - pad * 2
    draw.rounded_rectangle([x0, 40, px_x, 40 + 40], radius=20, fill=(255, 255, 255, 28))
    draw.text((x0 + pad, 48), label, font=pill_font, fill=(255, 255, 255, 235))
    px_x = x0 - 14

img.save(r"C:\Users\tempadmin\Desktop\sendpp-i18n\docs\banner.png")
print("banner written")
