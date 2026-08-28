"""Port of src/lib/color.ts."""
from __future__ import annotations


def is_light_color(hex_color: str) -> bool:
    """Relative-luminance check used to pick readable text against an
    arbitrary admin-chosen header/accent color."""
    r = int(hex_color[1:3], 16) / 255
    g = int(hex_color[3:5], 16) / 255
    b = int(hex_color[5:7], 16) / 255
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return luminance > 0.55
