"""Generate graphic overlay sprites (arrow.png) with Pillow at high fidelity."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def generate_arrow_sprite(out_path: Path) -> None:
    """Draw a bright yellow arrow pointing right with black outline, 220 px long.

    Sprite spec from 06 s10:
    - Points right
    - Length: 220 px
    - Fill: #FFD400
    - Outline: 6 px solid black (#000000)
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Use 4x supersampling for ultra-crisp antialiased edges
    scale = 4
    w = 220 * scale
    h = 130 * scale

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 4x Coordinates
    tip_x = (220 - 10) * scale
    tip_y = 65 * scale

    head_top_x = 135 * scale
    head_top_y = 12 * scale

    head_bot_x = 135 * scale
    head_bot_y = (130 - 12) * scale

    neck_top_x = 135 * scale
    neck_top_y = 42 * scale

    neck_bot_x = 135 * scale
    neck_bot_y = (130 - 42) * scale

    tail_x = 10 * scale
    tail_top_y = 42 * scale
    tail_bot_y = (130 - 42) * scale

    points = [
        (tip_x, tip_y),
        (head_top_x, head_top_y),
        (neck_top_x, neck_top_y),
        (tail_x, tail_top_y),
        (tail_x, tail_bot_y),
        (neck_bot_x, neck_bot_y),
        (head_bot_x, head_bot_y),
    ]

    outline_width = 6 * scale
    # Draw outline (stroke) then fill
    draw.polygon(points, fill="#FFD400", outline="#000000", width=outline_width)

    # Downscale with LANCZOS to exact 220x130 size
    final_img = img.resize((220, 130), resample=Image.Resampling.LANCZOS)
    final_img.save(out_path, format="PNG")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    overlays_dir = root / "assets" / "overlays"
    overlays_dir.mkdir(parents=True, exist_ok=True)

    arrow_path = overlays_dir / "arrow.png"
    generate_arrow_sprite(arrow_path)
    print(f"Generated arrow.png ({arrow_path.stat().st_size} bytes, dimensions {arrow_path})")


if __name__ == "__main__":
    main()
