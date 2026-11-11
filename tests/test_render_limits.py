"""Page images stay within MAX_PAGE_PIXELS however large the PDF page or photo is (review
M6). Pillow and pypdfium2 live only in the WSL OCR environment, so both are faked here."""

import sys
from pathlib import Path
from types import ModuleType

import pytest

import hklv_ocr.readers as readers


def test_normal_pages_render_at_300_dpi():
    assert readers.render_scale(595, 842) == pytest.approx(300 / 72)  # A4


def test_huge_pdf_page_is_rendered_at_a_lower_scale():
    scale = readers.render_scale(14400, 14400)  # 200 x 200 inches, the PDF maximum
    assert scale < 300 / 72
    assert (14400 * scale) ** 2 <= readers.MAX_PAGE_PIXELS * 1.0001


class FakeImage:
    def __init__(self, width, height):
        self.width, self.height = width, height

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def thumbnail(self, size):
        self.width, self.height = min(self.width, size[0]), min(self.height, size[1])

    def convert(self, mode):
        return self

    def verify(self):
        pass


@pytest.fixture
def fake_pil(monkeypatch):
    image_module = ModuleType("PIL.Image")
    image_module.MAX_IMAGE_PIXELS = None
    image_module.next_size = (100, 100)
    image_module.open = lambda path: FakeImage(*image_module.next_size)
    pil = ModuleType("PIL")
    pil.Image = image_module
    monkeypatch.setitem(sys.modules, "PIL", pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    return image_module


def test_huge_photo_is_shrunk_and_pillow_limit_is_set(fake_pil):
    fake_pil.next_size = (20_000, 10_000)  # 200 MP
    image = readers.render_page(Path("photo.jpg"), 0)
    assert fake_pil.MAX_IMAGE_PIXELS == readers.MAX_IMAGE_PIXELS
    assert image.width * image.height <= readers.MAX_PAGE_PIXELS
    assert image.width / image.height == pytest.approx(2.0, rel=0.01)


def test_photo_over_the_pillow_limit_is_unreadable(fake_pil):
    fake_pil.next_size = (20_000, 10_000)
    with pytest.raises(ValueError):
        readers.check_readable(Path("photo.jpg"))
    fake_pil.next_size = (4000, 3000)
    readers.check_readable(Path("photo.jpg"))


def test_pdf_render_uses_the_clamped_scale(monkeypatch, fake_pil):
    used = {}

    class Bitmap:
        def to_pil(self):
            return FakeImage(1, 1)

        def close(self):
            pass

    class Page:
        def get_size(self):
            return (14400.0, 14400.0)

        def render(self, scale):
            used["scale"] = scale
            return Bitmap()

        def close(self):
            pass

    class Document:
        def __init__(self, path):
            pass

        def __getitem__(self, index):
            return Page()

        def close(self):
            pass

    pdfium = ModuleType("pypdfium2")
    pdfium.PdfDocument = Document
    monkeypatch.setitem(sys.modules, "pypdfium2", pdfium)
    readers.render_page(Path("big.pdf"), 0)
    assert used["scale"] == pytest.approx(readers.render_scale(14400, 14400))
