"""Write packaging/planmarks.ico. No extra libraries."""

from __future__ import annotations

import struct
from pathlib import Path


def _pixels(size: int) -> bytes:
    """Bottom-up BGRA. Dark tile, brass circle, two bars."""
    cx = (size - 1) / 2
    cy = (size - 1) / 2
    outer = size * 0.34
    inner = size * 0.25
    bar_half = size * 0.22
    bar_thick = max(1.0, size * 0.055)
    rows = []
    for y in range(size - 1, -1, -1):
        for x in range(size):
            blue, green, red, alpha = 0x21, 0x1B, 0x18, 255
            dx = x - cx
            dy = y - cy
            dist = (dx * dx + dy * dy) ** 0.5
            y_top = (size - 1) - y
            brass = False
            if inner <= dist <= outer:
                brass = True
            if dist < inner:
                for center in (size * 0.40, size * 0.56):
                    if abs(y_top - center) <= bar_thick and abs(dx) <= bar_half:
                        brass = True
            if brass:
                blue, green, red = 0x3A, 0xA2, 0xE2
            rows.append(struct.pack("<BBBB", blue, green, red, alpha))
    return b"".join(rows)


def _image(size: int) -> bytes:
    xor_bitmap = _pixels(size)
    mask_row = ((size + 31) // 32) * 4
    mask = bytes(mask_row * size)
    header = struct.pack(
        "<IiiHHIIiiII",
        40,
        size,
        size * 2,
        1,
        32,
        0,
        len(xor_bitmap) + len(mask),
        0,
        0,
        0,
        0,
    )
    return header + xor_bitmap + mask


def write_icon(path: Path, sizes: tuple[int, ...] = (16, 32, 48)) -> None:
    images = [_image(size) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    offset = 6 + 16 * len(images)
    blobs = b""
    for size, image in zip(sizes, images):
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0,
            0,
            1,
            32,
            len(image),
            offset,
        )
        offset += len(image)
        blobs += image
    path.write_bytes(header + entries + blobs)


def main() -> None:
    destination = Path(__file__).resolve().parent / "planmarks.ico"
    write_icon(destination)


if __name__ == "__main__":
    main()
