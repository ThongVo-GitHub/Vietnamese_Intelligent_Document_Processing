# DocFlow VN — AI Engine Microservice (`ai-engine-0.1.0`)

Service xử lý độc lập cho bài toán Đọc tài liệu (PDF / Ảnh PNG, JPEG / Hóa đơn điện tử XML), Hybrid OCR tiếng Việt, Phân loại & Tách chứng từ (`contract`, `invoice`, `payment_request`, `unknown`), Chuẩn hóa số liệu và Bóc tách trường dữ liệu kèm tọa độ bằng chứng (`bbox`).

---

## 1. Thông số kỹ thuật đã chốt với Backend (Contract Handover)

| Hạng mục | Giá trị chốt | Ghi chú |
|---|---|---|
| **Port mặc định** | `8001` | Nội bộ Docker: `http://ai-engine:8001` |
| **Healthcheck Endpoint** | `GET /health` | Trả `200 OK` `{"status": "ok", "service": "ai-engine", "engine_version": "ai-engine-0.1.0"}` |
| **Analyze Endpoint** | `POST /analyze` | `Content-Type: multipart/form-data` |
| **Multipart Field Name** | `file` | Hỗ trợ `PDF`, `PNG`, `JPEG`, `XML` (tối đa `10 MB`) |
| **Timeout khuyến nghị** | `60s` (`AI_ENGINE_TIMEOUT_SECONDS=60`) | PDF điện tử / XML: `5–50 ms`; Ảnh / PDF scan (OCR): `2–8s` (GPU) hoặc `5–20s` (CPU) |
| **Quy ước lỗi HTTP** | `400`, `413`, `415`, `422`, `500` | `400`: File rỗng; `413`: Vượt 10MB; `415`: Sai định dạng; `422`: Thiếu field `file`; `500`: Lỗi xử lý nội bộ |
| **Quy ước `bbox`** | Top-Left `[0.0 .. 1.0]` | `0 <= x1 <= x2 <= 1`, `0 <= y1 <= y2 <= 1`. Đã tự chuyển hệ tọa độ PDF gốc dưới-trái sang trên-trái |
| **Ngưỡng `needs_review`** | `confidence < 0.80` | Biến môi trường `AI_NEEDS_REVIEW_THRESHOLD=0.80` (hoặc khi LLM fallback / không parse được số tiền bằng chữ) |
| **Giá trị `source`** | `text_layer`, `ocr`, `llm` | Phản ánh đúng nguồn trích xuất thực tế của từng trường |

---

## 2. Danh sách trường trích xuất (`ExtractedField.name`)

Khớp 100% với `REQUIRED_FIELDS` và luật đối chiếu trong `backend/app/services/reconciliation_rules.py`:

- **Hợp đồng (`contract`):**
  - Bắt buộc: `contract_number`, `tax_id` (MST Bên bán/Bên B), `total_amount`, `currency`
  - Mở rộng: `buyer_tax_id` (MST Bên mua/Bên A), `issue_date`, `contract_date`, `supplier_name`, `customer_name`, `subtotal`, `vat_rate`, `vat_amount`, `amount_in_words` (`normalized_value` chuyển thành chuỗi số để đối chiếu chéo với `total_amount`).
- **Hóa đơn (`invoice`):**
  - Bắt buộc: `invoice_number`, `contract_number`, `tax_id`, `subtotal`, `vat_rate`, `vat_amount`, `total_amount`, `currency`
  - Mở rộng: `buyer_tax_id`, `issue_date`, `supplier_name`, `customer_name`, `amount_in_words`.
- **Đề nghị thanh toán (`payment_request`):**
  - Bắt buộc: `invoice_number`, `payment_amount`, `currency`
  - Mở rộng: `request_number`, `payment_request_number`, `request_date`, `issue_date`, `contract_number`, `tax_id`, `payee_name`, `bank_account`, `bank_name`, `total_amount`, `amount_in_words`.
  - *Lưu ý phạm vi demo:* Không tự gán `phiếu chi`, `ủy nhiệm chi` hoặc `biên lai` thành `payment_request` (trả về `unknown`).

---

## 3. Danh sách Model Open-Source & Cách tải trước (Preload)

Tất cả thư viện và trọng số đều tuân thủ giấy phép mã nguồn mở hợp lệ (Apache-2.0 / MIT / BSD, không dùng AGPL):

1. **Text Detection:** `RapidOCR` (PP-OCRv4 ONNX qua `rapidocr-onnxruntime`, Apache-2.0) — trọng số ONNX gọn nhẹ đi kèm sẵn khi cài pip (`~15 MB`), không cần tải thủ công.
2. **Vietnamese Text Recognition (Tùy chọn nâng cao độ chính xác dấu tiếng Việt):** `VietOCR` (`vgg_seq2seq`, MIT, `~90 MB`).
   - Lệnh tải trước trọng số model vào cache để khi demo offline không cần mạng:
     ```powershell
     python -c "from vietocr.tool.config import Cfg; from vietocr.tool.predictor import Predictor; c = Cfg.load_config_from_name('vgg_seq2seq'); c['device']='cpu'; Predictor(c)"
     ```
3. **LLM Fallback cho chứng từ bố cục lạ (Tùy chọn):** `Qwen2.5:1.5b` hoặc `Qwen2.5:3b` chạy qua `Ollama` (Apache-2.0) khi cấu hình biến môi trường `OLLAMA_BASE_URL=http://ollama:11434` và `OLLAMA_MODEL=qwen2.5:1.5b`.

---

## 4. Yêu cầu phần cứng (RAM / VRAM)

- **Chế độ tiêu chuẩn (RapidOCR ONNX + Rule/Spatial Extractor):**
  - RAM: `~800 MB – 1.5 GB`, không bắt buộc GPU (chạy tốt trên CPU Docker).
- **Chế độ đầy đủ (kèm VietOCR GPU + Ollama Qwen2.5:1.5b/3b):**
  - RAM hệ thống: tối thiểu `8 GB` (khuyến nghị `16 GB`).
  - VRAM GPU: `~1.5 GB` cho VietOCR + `~2.2 GB` cho `qwen2.5:3b` (chạy mượt trên RTX 3050 Ti 4GB VRAM trở lên, tự động fallback về CPU nếu container không gắn GPU).

---

## 5. Cách chạy độc lập & Kiểm thử

```powershell
# Cài đặt dependencies
python -m pip install -e "./ai-engine[dev]"

# Chạy AI Engine service tại cổng 8001
python -m uvicorn app.main:app --app-dir ai-engine --host 0.0.0.0 --port 8001

# Kiểm tra health
Invoke-RestMethod http://localhost:8001/health
```
