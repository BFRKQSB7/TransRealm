"""Convert the generated PNG to a Windows ICO using the existing Qt runtime."""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QImageWriter

ASSETS = Path(__file__).resolve().parents[1] / "src/transrealm/ui/assets"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main() -> None:
    source = QImage(str(ASSETS / "transrealm.png"))
    if source.isNull() or source.width() != source.height() or not source.hasAlphaChannel():
        raise SystemExit("The source icon must be a square PNG with transparency.")
    frames = []
    for size in SIZES:
        frame = source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not QImageWriter(buffer, b"PNG").write(frame):
            raise SystemExit(f"Could not encode the {size}px icon.")
        frames.append(buffer.data().data())
    offset = 6 + 16 * len(SIZES)
    content = bytearray(struct.pack("<HHH", 0, 1, len(SIZES)))
    for size, frame_bytes in zip(SIZES, frames, strict=True):
        content.extend(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0,
                                   1, 32, len(frame_bytes), offset))
        offset += len(frame_bytes)
    for frame_bytes in frames:
        content.extend(frame_bytes)
    target = ASSETS / "transrealm.ico"
    target.write_bytes(content)
    print(f"Created {target}: {', '.join(map(str, SIZES))}px")


if __name__ == "__main__":
    main()
