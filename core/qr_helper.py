"""
core/qr_helper.py
Generates a QR code image (PIL Image) for a given URL, so the user can scan
it with their phone camera instead of typing the address.
"""

import base64
import io

import qrcode
from PIL import Image

from logger import get_logger

log = get_logger()


def make_qr_image(url: str, box_size: int = 8, border: int = 2) -> Image.Image:
    """Return a PIL Image containing a QR code that encodes `url`."""
    log.debug("Generating QR code for URL: %s", url)
    qr = qrcode.QRCode(
        version=None,  # auto-size to fit the data
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    return img.convert("RGB")


def make_qr_data_uri(url: str, box_size: int = 8, border: int = 2) -> str:
    """
    Return the QR code as a data: URI (base64 PNG), for embedding directly
    in an <img> tag in server-rendered HTML - no external JS library or
    internet access needed, works the same on LAN or over a public tunnel.
    """
    img = make_qr_image(url, box_size=box_size, border=border)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"

