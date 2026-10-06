from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_LANGUAGE = "vie+eng"
DEFAULT_PSM = 6
ALLOWED_PSM = (3, 6, 11)
DEFAULT_IMAGE_PATH = (
    Path(__file__).resolve().parents[2] / "runtime" / "images1" / "ảnh1.png"
)
OCR_RESULT: str | None = None


def find_tesseract() -> str | None:
    configured = os.environ.get("TESSERACT_CMD")
    candidates = [configured] if configured else []
    candidates.extend(
        (shutil.which("tesseract"), "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract")
    )

    for candidate in candidates:
        if not candidate:
            continue
        executable = shutil.which(candidate) or candidate
        if Path(executable).is_file():
            return executable
    return None


def clean_path(value: str) -> Path:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return Path(value).expanduser()


def available_languages(tesseract: str) -> list[str]:
    result = subprocess.run(
        [tesseract, "--list-langs"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or "Không đọc được danh sách ngôn ngữ Tesseract."
        )
    return [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]


def recognize(
    image_path: str | Path = DEFAULT_IMAGE_PATH,
    output_path: str | Path | None = None,
    language: str = DEFAULT_LANGUAGE,
    psm: int = DEFAULT_PSM,
    whitelist: str | None = None,
) -> str:
    global OCR_RESULT

    OCR_RESULT = None
    image_path = clean_path(str(image_path))

    if not image_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy ảnh đầu vào: {image_path}")
    if "captcha" in str(image_path).casefold():
        raise ValueError(
            "Công cụ này chỉ dùng cho ảnh văn bản thông thường, không xử lý CAPTCHA."
        )

    tesseract = find_tesseract()
    if not tesseract:
        raise FileNotFoundError(
            "Không tìm thấy Tesseract. Cài bằng `brew install tesseract tesseract-lang` "
            "hoặc đặt biến TESSERACT_CMD."
        )

    languages = available_languages(tesseract)
    requested = language.split("+")
    missing = [item for item in requested if item not in languages]
    if missing:
        raise ValueError(
            f"Chưa cài ngôn ngữ OCR: {', '.join(missing)}. "
            f"Ngôn ngữ hiện có: {', '.join(languages) or 'không có'}."
        )

    cmd = [tesseract, str(image_path), "stdout", "-l", language, "--psm", str(psm)]
    if whitelist:
        cmd.extend(["-c", f"tessedit_char_whitelist={whitelist}"])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "Tesseract không xử lý được ảnh."
        raise RuntimeError(message[-1200:])

    OCR_RESULT = result.stdout.strip()

    if output_path is not None:
        output_file = clean_path(str(output_path)).with_suffix(".txt")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(OCR_RESULT + "\n", encoding="utf-8")
        print(f"Đã lưu văn bản vào: {output_file}")

    return OCR_RESULT


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Nhận diện chữ trong ảnh, có thể lưu kết quả thành tệp .txt."
    )
    parser.add_argument(
        "--input",
        help=f"Đường dẫn ảnh đầu vào (mặc định: {DEFAULT_IMAGE_PATH}).",
    )
    parser.add_argument("--output", help="Tùy chọn lưu thêm kết quả vào tệp text.")
    parser.add_argument(
        "--lang",
        default=DEFAULT_LANGUAGE,
        help=f"Ngôn ngữ OCR (mặc định: {DEFAULT_LANGUAGE}).",
    )
    parser.add_argument(
        "--psm",
        type=int,
        choices=ALLOWED_PSM,
        default=DEFAULT_PSM,
        help="Bố cục ảnh: 3 tự nhận diện, 6 một khối chữ, 11 chữ rời rạc.",
    )
    args = parser.parse_args()

    try:
        image_path = clean_path(args.input) if args.input else DEFAULT_IMAGE_PATH
        output_path = clean_path(args.output) if args.output else None
        text = recognize(image_path, output_path, args.lang, args.psm)

        print("\n--- Kết quả OCR ---")
        print(text or "(Không nhận diện được chữ trong ảnh.)")
        return 0
    except (EOFError, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())