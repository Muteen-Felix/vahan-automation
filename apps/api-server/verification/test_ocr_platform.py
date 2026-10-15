from importlib import import_module
from pathlib import Path

import pytest


OCR_MODULES = (
    "app.ocr.ocr_to_text",
    "app.ocr.ocr_to_text_1",
    "app.ocr.ocr_to_text_2",
    "app.ocr.ocr_to_text_3",
    "app.ocr.ocr_to_text_4",
    "app.ocr.ocr_to_text_5",
)


@pytest.mark.parametrize("module_name", OCR_MODULES)
def test_finds_default_windows_tesseract_install(monkeypatch, tmp_path: Path, module_name: str) -> None:
    executable = tmp_path / "Tesseract-OCR" / "tesseract.exe"
    executable.parent.mkdir()
    executable.write_text("fixture", encoding="utf-8")
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    module = import_module(module_name)
    monkeypatch.setattr(module.shutil, "which", lambda _command: None)

    assert module.find_tesseract() == str(executable)
