from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "downloader.py"
spec = spec_from_file_location("downloader", SCRIPT_PATH)
assert spec and spec.loader
_downloader = module_from_spec(spec)
sys.modules["downloader"] = _downloader
spec.loader.exec_module(_downloader)


def test_safe_supplier_name():
    assert _downloader._safe_supplier_name("Shop Vkus #1") == "Shop_Vkus_1"


def test_guess_ext_from_url_and_content_type():
    assert _downloader._guess_ext("https://x/y.png", None) == ".png"
    assert _downloader._guess_ext("https://x/y", "image/webp") == ".webp"


def test_iter_input_rows_txt(tmp_path: Path):
    p = tmp_path / "urls.txt"
    p.write_text("https://a/a.jpg\nnot_url\nhttps://b/b.png\n", encoding="utf-8")
    rows = list(_downloader._iter_input_rows(p, "image_url", "supplier"))
    assert rows == [("https://a/a.jpg", "default"), ("https://b/b.png", "default")]
