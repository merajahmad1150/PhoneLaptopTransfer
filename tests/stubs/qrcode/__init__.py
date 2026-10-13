"""TEST-ONLY stand-in for the qrcode package (the sandbox has no internet to install the real
qrcode 8.x). Mimics the API surface qr_helper.py uses; it does NOT produce scannable codes."""
from PIL import Image
import hashlib
class constants: ERROR_CORRECT_M = 0
class _Img:
    def __init__(self, im): self._im = im
    def get_image(self): return self._im
class QRCode:
    def __init__(self, version=None, error_correction=0, box_size=10, border=4): self.box, self.border, self.data = box_size, border, ""
    def add_data(self, d): self.data += d
    def make(self, fit=True): pass
    def make_image(self, fill_color="black", back_color="white"):
        n = 25; h = hashlib.sha256(self.data.encode()).digest()
        im = Image.new("RGB", ((n + 2 * self.border) * self.box,) * 2, back_color)
        for y in range(n):
            for x in range(n):
                if h[(x * n + y) % 32] >> (x % 8) & 1:
                    for dy in range(self.box):
                        for dx in range(self.box): im.putpixel(((x + self.border) * self.box + dx, (y + self.border) * self.box + dy), (0, 0, 0))
        return _Img(im)
    def print_ascii(self, out=None, invert=False): out.write("[stub qr]\n")
