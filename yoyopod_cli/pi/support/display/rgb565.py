"""RGB565 framebuffer helpers for LVGL-backed display adapters."""

from __future__ import annotations

import base64
import struct
import zlib
from dataclasses import dataclass, field


def rgb888_to_rgb565_bytes(color: tuple[int, int, int]) -> bytes:
    """Pack one RGB888 tuple into big-endian RGB565 bytes."""

    red, green, blue = color
    value = ((int(red) & 0xF8) << 8) | ((int(green) & 0xFC) << 3) | (int(blue) >> 3)
    return bytes(((value >> 8) & 0xFF, value & 0xFF))


def _rgb565_bytes_to_rgb888_bytes(pixel_data: bytes) -> bytes:
    """Decode big-endian RGB565 pixel data into packed RGB888 bytes."""

    rgb888 = bytearray((len(pixel_data) // 2) * 3)
    write_index = 0
    for index in range(0, len(pixel_data), 2):
        value = (pixel_data[index] << 8) | pixel_data[index + 1]
        red = ((value >> 11) & 0x1F) * 255 // 31
        green = ((value >> 5) & 0x3F) * 255 // 63
        blue = (value & 0x1F) * 255 // 31
        rgb888[write_index : write_index + 3] = bytes((red, green, blue))
        write_index += 3
    return bytes(rgb888)


def rgb565_bytes_to_png(width: int, height: int, pixel_data: bytes) -> bytes:
    """Encode a full RGB565 frame as a PNG image."""

    if len(pixel_data) != width * height * 2:
        raise ValueError("RGB565 frame size does not match dimensions")

    rgb888 = _rgb565_bytes_to_rgb888_bytes(pixel_data)
    scanlines = bytearray()
    row_stride = width * 3
    for row in range(height):
        start = row * row_stride
        scanlines.append(0)  # PNG filter type 0
        scanlines.extend(rgb888[start : start + row_stride])

    compressed = zlib.compress(bytes(scanlines), level=6)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", header),
            chunk(b"IDAT", compressed),
            chunk(b"IEND", b""),
        )
    )


@dataclass(slots=True)
class Rgb565FrameBuffer:
    """Keep a full display-sized RGB565 frame in Python memory."""

    width: int
    height: int
    data: bytearray = field(init=False)
    dirty: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.data = bytearray(self.width * self.height * 2)

    def clear(self, color: tuple[int, int, int]) -> None:
        """Fill the entire frame with one RGB888 color."""

        pixel = rgb888_to_rgb565_bytes(color)
        self.data[:] = pixel * (self.width * self.height)
        self.dirty = True

    def paste_region(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        pixel_data: bytes,
    ) -> None:
        """Copy one RGB565 region into the full-frame buffer."""

        if width <= 0 or height <= 0:
            return
        expected_size = width * height * 2
        if len(pixel_data) != expected_size:
            raise ValueError("RGB565 region size does not match dimensions")
        if x < 0 or y < 0 or x + width > self.width or y + height > self.height:
            raise ValueError("RGB565 region falls outside the framebuffer bounds")

        source_stride = width * 2
        destination_stride = self.width * 2
        for row in range(height):
            source_start = row * source_stride
            source_end = source_start + source_stride
            destination_start = ((y + row) * destination_stride) + (x * 2)
            destination_end = destination_start + source_stride
            self.data[destination_start:destination_end] = pixel_data[source_start:source_end]
        self.dirty = True

    def to_png_bytes(self) -> bytes:
        """Encode the current full frame as PNG bytes."""

        return rgb565_bytes_to_png(self.width, self.height, bytes(self.data))

    def to_png_base64(self) -> str:
        """Encode the current full frame as a base64 PNG payload."""

        return base64.b64encode(self.to_png_bytes()).decode("ascii")
