from __future__ import annotations

import asyncio
import base64
import binascii
import re
from string import Formatter
from pathlib import Path
from uuid import UUID, uuid4


_DATA_URL = re.compile(r"data:(image/png|image/jpeg|image/webp);base64,([A-Za-z0-9+/]*={0,2})\Z")
_IMAGE_TYPES = {
    "image/png": ("png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/jpeg": ("jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    "image/webp": ("webp", lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"),
}
_MAX_IMAGE_BYTES = 750_000
_IMAGE_EXTENSIONS = {image_type[0] for image_type in _IMAGE_TYPES.values()}
_DEFAULT_PATH_TEMPLATE = "ảnh1"


class CaptchaImageStore:

    def __init__(  # Khởi tạo bộ lưu ảnh với thư mục gốc và mẫu đường dẫn tùy chỉnh.
        self,  # Tham chiếu tới đối tượng CaptchaImageStore hiện tại.
        directory: str | Path,
        path_template: str = _DEFAULT_PATH_TEMPLATE,  # Mẫu đường dẫn tương đối, có thể chứa {job_id}.
    ) -> None:  # Hàm khởi tạo không trả về giá trị.
        self.directory = Path(directory)  # Chuẩn hóa thư mục gốc thành đối tượng Path.
        self.path_template = path_template  # Lưu mẫu đường dẫn để dùng khi ghi từng ảnh.

    async def save(self, job_id: UUID, image_data_url: str) -> Path:  # Lưu ảnh bất đồng bộ và trả lại đường dẫn tệp.
        return await asyncio.to_thread(self._save, job_id, image_data_url)  # Chạy thao tác tệp đồng bộ trong thread nền.

    def _save(self, job_id: UUID, image_data_url: str) -> Path:  # Giải mã, kiểm tra và ghi ảnh CAPTCHA vào đĩa.
        match = _DATA_URL.fullmatch(image_data_url)  # Kiểm tra dữ liệu có đúng định dạng Data URL ảnh được hỗ trợ không.
        if not match:  # Nếu dữ liệu không khớp định dạng cho phép thì dừng xử lý.
            raise ValueError("Unsupported CAPTCHA image data URL.")  # Báo lỗi khi Data URL không hợp lệ hoặc không được hỗ trợ.

        mime_type, encoded = match.groups()  # Tách loại MIME và phần dữ liệu ảnh đã mã hóa Base64.
        try:  # Bắt đầu giải mã phần Base64 thành byte ảnh.
            image_bytes = base64.b64decode(encoded, validate=True)  # Giải mã nghiêm ngặt để từ chối ký tự Base64 sai.
        except (binascii.Error, ValueError) as error:  # Bắt lỗi khi chuỗi Base64 không thể giải mã.
            raise ValueError("Invalid CAPTCHA image data.") from error  # Chuyển lỗi thành thông báo dữ liệu ảnh không hợp lệ.

        extension, signature_check = _IMAGE_TYPES[mime_type]  # Lấy phần mở rộng và hàm kiểm tra chữ ký theo MIME.
        if (  # Kiểm tra ảnh có dữ liệu, không vượt giới hạn dung lượng và đúng chữ ký định dạng.
            not image_bytes  # Từ chối tệp ảnh rỗng.
            or len(image_bytes) > _MAX_IMAGE_BYTES  # Từ chối ảnh vượt quá dung lượng tối đa.
            or not signature_check(image_bytes)  # Từ chối byte ảnh không khớp chữ ký của MIME đã khai báo.
        ):  # Kết thúc điều kiện xác thực byte ảnh.
            raise ValueError("Invalid or oversized CAPTCHA image.")  # Báo lỗi nếu ảnh rỗng, quá lớn hoặc sai định dạng.

        relative_stem = self._relative_path_stem(job_id)  # Tạo phần đường dẫn tương đối theo mẫu đã cấu hình.
        image_stem = self.directory / relative_stem  # Ghép đường dẫn tương đối với thư mục gốc lưu ảnh.
        job_directory = image_stem.parent  # Lấy thư mục chứa ảnh theo mẫu đường dẫn.
        job_directory.mkdir(parents=True, exist_ok=True)  # Tạo các thư mục cha nếu chúng chưa tồn tại.
        image_path = Path(f"{image_stem}.{extension}")  # Thêm phần mở rộng đúng với định dạng ảnh thực tế.
        temporary_path = job_directory / f".{image_stem.name}-{uuid4().hex}.tmp"  # Tạo tên tệp tạm duy nhất để tránh ghi dở lên ảnh cũ.
        try:  # Ghi ảnh tạm trước rồi mới thay thế ảnh đích một cách nguyên tử.
            temporary_path.write_bytes(image_bytes)  # Ghi byte ảnh đã giải mã vào tệp tạm.
            temporary_path.replace(image_path)  # Đổi tên tệp tạm thành đường dẫn ảnh cuối cùng.
        finally:  # Luôn dọn tệp tạm kể cả khi thao tác ghi hoặc đổi tên gặp lỗi.
            temporary_path.unlink(missing_ok=True)  # Xóa tệp tạm nếu nó vẫn còn tồn tại.

        for stale_image in job_directory.iterdir():  # Duyệt các mục trong thư mục để tìm bản cũ cùng tên gốc.
            if (  # Chỉ chọn tệp ảnh cũ có cùng tên gốc nhưng khác phần mở rộng hoặc nội dung hiện tại.
                stale_image != image_path  # Giữ nguyên tệp ảnh mới vừa được ghi.
                and stale_image.is_file()  # Chỉ xử lý tệp, bỏ qua thư mục con.
                and stale_image.name.startswith(f"{image_stem.name}.")  # Chỉ xét tệp có cùng tên gốc với ảnh hiện tại.
                and stale_image.suffix.lstrip(".") in _IMAGE_EXTENSIONS  # Chỉ xóa các phần mở rộng ảnh được hỗ trợ.
            ):  # Kết thúc điều kiện nhận diện ảnh cũ.
                stale_image.unlink()  # Xóa ảnh cũ để mỗi đường dẫn chỉ giữ phiên bản hiện hành.
        return image_path  # Trả về đường dẫn ảnh cuối cùng vừa được lưu.

    def _relative_path_stem(self, job_id: UUID) -> Path:  # Tạo phần đường dẫn tùy chỉnh và kiểm tra an toàn trước khi ghi.
        """Mở rộng mẫu đường dẫn tương đối, chưa kèm phần mở rộng của ảnh."""  # Giải thích kết quả của hàm trợ giúp.
        try:  # Kiểm tra các placeholder và mở rộng mẫu bằng UUID của job.
            for _, field_name, format_spec, conversion in Formatter().parse(self.path_template):  # Duyệt từng trường định dạng trong mẫu.
                if field_name is not None and field_name != "job_id":  # Chỉ cho phép placeholder {job_id}.
                    raise ValueError("Only the {job_id} placeholder is supported.")  # Báo lỗi nếu mẫu dùng placeholder khác.
                if format_spec or conversion:  # Từ chối định dạng hoặc chuyển đổi đặc biệt trong placeholder.
                    raise ValueError("Format specifiers are not supported in the CAPTCHA path template.")  # Báo mẫu có cú pháp định dạng không hỗ trợ.
            rendered = self.path_template.format(job_id=str(job_id))  # Thay {job_id} bằng UUID dạng chuỗi.
        except (IndexError, KeyError, ValueError) as error:  # Bắt lỗi cú pháp hoặc placeholder trong mẫu đường dẫn.
            raise ValueError("Invalid CAPTCHA image path template.") from error  # Báo lỗi mẫu đường dẫn không hợp lệ.

        parts = rendered.split("/")  # Tách các thành phần đường dẫn để kiểm tra từng đoạn.
        relative_path = Path(rendered)  # Chuyển chuỗi đường dẫn thành đối tượng Path.
        if (  # Từ chối đường dẫn rỗng, tuyệt đối hoặc có thành phần thoát khỏi thư mục gốc.
            not rendered  # Không chấp nhận mẫu tạo ra chuỗi rỗng.
            or "\\" in rendered  # Không chấp nhận dấu gạch chéo ngược để tránh cú pháp đường dẫn kiểu Windows.
            or relative_path.is_absolute()  # Không cho phép mẫu ghi ra ngoài thư mục gốc bằng đường dẫn tuyệt đối.
            or any(part in {"", ".", ".."} for part in parts)  # Từ chối đoạn rỗng, dấu chấm hoặc dấu chấm đôi.
        ):  # Kết thúc điều kiện kiểm tra an toàn đường dẫn.
            raise ValueError("CAPTCHA image path template must be a safe relative path stem.")  # Báo lỗi khi mẫu có thể thoát khỏi thư mục gốc.
        return relative_path  # Trả về đường dẫn tương đối đã được xác thực.
