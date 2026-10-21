# DocFlow VN

Hệ thống xử lý tài liệu thông minh dành cho hợp đồng, hóa đơn, biểu mẫu và hồ sơ điện tử tiếng Việt.

DocFlow VN hướng tới việc tự động phân loại tài liệu, trích xuất và chuẩn hóa dữ liệu, đối chiếu thông tin, phát hiện trường còn thiếu hoặc không nhất quán, đồng thời hỗ trợ tìm kiếm trên kho hồ sơ.

## Trạng thái dự án

Dự án đang ở giai đoạn xây dựng nền tảng.

Đã hoàn thành:

- FastAPI backend và tài liệu OpenAPI/Swagger.
- Health check và database readiness check.
- PostgreSQL kết hợp pgvector.
- Dockerfile và Docker Compose.
- Pydantic schema cho OCR block, bounding box và kết quả phân tích.
- Unit test cho API và schema dữ liệu.

Đang phát triển:

- Upload hồ sơ và quản lý processing job.
- Tiền xử lý hình ảnh bằng OpenCV.
- OCR tiếng Việt và nhận diện bảng.
- Phân loại hợp đồng, hóa đơn và biểu mẫu.
- Trích xuất dữ liệu có cấu trúc.
- Chuẩn hóa ngày, tiền tệ và mã số thuế.
- Đối chiếu dữ liệu và sinh cảnh báo.
- Tìm kiếm ngữ nghĩa bằng vector embedding.
- Giao diện hiển thị tài liệu và bounding box.

## Luồng xử lý mục tiêu

```text
Tài liệu PDF/ảnh
        |
        v
Tiền xử lý hình ảnh
        |
        v
OCR + Bounding Box
        |
        v
Phân loại tài liệu
        |
        v
Trích xuất và chuẩn hóa dữ liệu
        |
        v
Đối chiếu và cảnh báo
        |
        v
PostgreSQL + pgvector
        |
        v
API và giao diện người dùng
```

## Công nghệ

| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| Backend API | FastAPI | Cung cấp API và OpenAPI |
| Data contract | Pydantic | Kiểm tra cấu trúc dữ liệu |
| ORM | SQLAlchemy | Truy cập cơ sở dữ liệu |
| Migration | Alembic | Quản lý thay đổi schema |
| Database | PostgreSQL | Lưu hồ sơ và kết quả xử lý |
| Vector search | pgvector | Lưu embedding và tìm kiếm ngữ nghĩa |
| Testing | pytest | Kiểm thử tự động |
| Container | Docker Compose | Chạy các dịch vụ đồng nhất |

Các thành phần OCR, NLP và AI sẽ được bổ sung ở các giai đoạn tiếp theo.

## Yêu cầu hệ thống

Cách chạy được khuyến nghị:

- Git
- Docker Desktop với Docker Compose
- Tối thiểu 4 GB RAM trống

Để phát triển backend trực tiếp:

- Python 3.11 trở lên
- Python virtual environment

## Khởi động nhanh bằng Docker

### 1. Clone repository

```bash
git clone https://github.com/ThongVo-GitHub/Vietnamese_Intelligent_Document_Processing.git
cd Vietnamese_Intelligent_Document_Processing
```

### 2. Tạo file môi trường

Trên PowerShell:

```powershell
Copy-Item .env.example .env
```

Không commit file `.env` lên Git.

### 3. Khởi động hệ thống

```powershell
docker compose up -d --build
```

### 4. Kích hoạt pgvector

Lệnh này chỉ cần thiết khi khởi tạo database mới:

```powershell
docker compose exec postgres psql -U docflow -d docflow -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 5. Kiểm tra dịch vụ

```powershell
docker compose ps
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/health/ready
```

Kết quả readiness thành công:

```json
{
  "status": "ok",
  "service": "backend",
  "database": "connected"
}
```

Tài liệu API:

- Swagger UI: http://localhost:8000/docs
- OpenAPI JSON: http://localhost:8000/openapi.json

### 6. Dừng hệ thống

```powershell
docker compose down
```

Lệnh trên dừng container nhưng giữ lại dữ liệu PostgreSQL.

## Phát triển backend trên Windows

Tạo và kích hoạt virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Cài thư viện:

```powershell
python -m pip install --upgrade pip
python -m pip install -e "./backend[dev]"
```

Chạy test:

```powershell
python -m pytest backend/tests -q
```

Chạy backend trực tiếp:

```powershell
python -m uvicorn app.main:app --app-dir backend --reload
```

## Các lệnh Makefile

Nếu máy đã cài GNU Make:

```bash
make install
make test
make check
make compose-up
make compose-ps
make compose-logs
make compose-down
```

Trên Windows chưa cài GNU Make, có thể sử dụng trực tiếp các lệnh Python và Docker Compose tương ứng.

## API hiện có

| Method | Endpoint | Mục đích |
|---|---|---|
| GET | `/` | Thông tin dịch vụ |
| GET | `/health` | Kiểm tra backend đang hoạt động |
| GET | `/health/ready` | Kiểm tra backend kết nối database |

## Cấu trúc repository

```text
.
├── ai-engine/          # Dịch vụ OCR, NLP và AI trong giai đoạn tiếp theo
├── backend/            # FastAPI backend
│   ├── app/
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
├── docs/               # Tài liệu kỹ thuật
├── frontend/           # Giao diện trong giai đoạn tiếp theo
├── docker-compose.yml
├── Makefile
└── README.md
```

## Bảo mật

- Không commit `.env`, mật khẩu, token hoặc tài liệu nhạy cảm.
- Dữ liệu mẫu cần được ẩn thông tin cá nhân trước khi đưa vào repository.
- Cấu hình mặc định chỉ phục vụ môi trường phát triển, không dùng trực tiếp cho production.

## Trao đổi và báo lỗi

Sử dụng GitHub Issues để báo lỗi, đề xuất tính năng hoặc thảo luận kỹ thuật:

https://github.com/ThongVo-GitHub/Vietnamese_Intelligent_Document_Processing/issues

## Giấy phép

Dự án được phát hành theo giấy phép MIT. Xem file [LICENSE](LICENSE).