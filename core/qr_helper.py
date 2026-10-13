"""
core/qr_helper.py
QR codes (qrcode 8.x + Pillow). PIL image for the GUI, a data: URI for web
pages, and a text version for the console.
"""

import base64
import io

import qrcode
from PIL import Image

from logger import get_logger

log = get_logger()


def _build(url: str, box_size: int, border: int):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr


def make_qr_image(url: str, box_size: int = 8, border: int = 2, target_px: int = None) -> Image.Image:
    """Return a PIL Image with a QR code encoding `url`.

    With `target_px` the code is scaled by a WHOLE-NUMBER factor using nearest-neighbour
    (so every module stays razor-sharp and easy to scan) to the largest size that fits."""
    log.debug("QR code for %s%s", url, f" ({target_px}px)" if target_px else "")
    if target_px:
        base = _to_pil(_build(url, 1, border))
        k = max(1, target_px // base.width)
        return base.resize((base.width * k, base.height * k), Image.NEAREST)
    return _to_pil(_build(url, box_size, border))


def _to_pil(qr) -> Image.Image:
    img = qr.make_image(fill_color="black", back_color="white")
    pil = img.get_image() if hasattr(img, "get_image") else img
    return pil.convert("RGB")


def make_qr_data_uri(url: str, box_size: int = 10, border: int = 2) -> str:
    img = make_qr_image(url, box_size=box_size, border=border)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def make_qr_text(url: str) -> str:
    """Console-friendly QR using block characters (needs a UTF-8 console)."""
    qr = _build(url, 1, 1)
    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    return buf.getvalue()
