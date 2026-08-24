# Danh sách port sử dụng trong SAN-90

## 1. `tcp://0.0.0.0:5557` — AI Image Publisher (backend → detector)

- **Bind bởi:** `backend/ai_stream/image_publisher.py` (PUSH socket), cấu hình qua `AI_STREAM_BIND` (`backend/ai_stream/config.py:30`).
- **Connect bởi (PULL):** `tools/yolo_detection.py`, `tools/ai_gray8_receiver.py`.
- **Nội dung:** multipart 2 phần — `[metadata JSON, ảnh GRAY8 raw bytes]`, định dạng bởi `backend/ai_stream/protocol.py` (`build_metadata` / `validate_multipart`):
  - Ảnh: 640×640, 1 kênh, `uint8`, `C order` (409,600 bytes).
  - Metadata JSON gồm: `sequence`, `timestamp_ns`, `center/start/stop_frequency_hz`, `power_profile`, `power_min_dbm`/`power_max_dbm`, `power_range_db`, `power_range_generation`, `db_per_gray_level`, `trace_count`, `first/last_trace_sequence`, `capture_start/end_timestamp_ns`, `configuration_generation`, `clipped_low_ratio`/`clipped_high_ratio`, `image_min_dbm`/`image_max_dbm`, v.v.
- **Mục đích:** truyền ảnh waterfall GRAY8 (chuẩn hoá theo dBm) từ backend sang `tools/yolo_detection.py` để chạy YOLO.

## 2. `tcp://127.0.0.1:5558` — AI Detection Subscriber (detector → backend, nhẹ)

- **Bind bởi (PUB):** `tools/yolo_detection.py`, tham số `--publish` (mặc định `tcp://127.0.0.1:5558`).
- **Connect bởi (SUB):** `backend/ai_detection.py` (`AiDetectionSubscriber`), qua `backend/api/service.py`, cấu hình endpoint bằng biến môi trường `AI_DETECTION_SUB_URL` (mặc định `tcp://127.0.0.1:5558`), bật bằng `AI_DETECTION_SUB_ENABLED`.
- **Nội dung:** JSON string do `publish_result()` (`tools/yolo_detection.py`) tạo:
  ```json
  {
    "sequence": 123,
    "timestamp_ns": 169...,
    "generated_at": 169...,
    "detections": [
      {"class_id": 0, "label": "FR_SKY", "confidence": 0.91, "bbox": [x1, y1, x2, y2]}
    ],
    "label_freq_ranges_hz": {
      "FR_SKY": {"start_hz": 2400000000.0, "stop_hz": 2483000000.0}
    }
  }
  ```
- **Giới hạn ở backend:** `MAX_MESSAGE_BYTES = 256 * 1024`, `MAX_DETECTIONS = 128` (`backend/ai_detection.py`).
- **Mục đích:** đẩy kết quả detect (bounding box, nhãn, độ tin cậy, dải tần) từ detector về backend để forward tiếp cho client qua WebSocket (message type `0x11`, xem mục 4) — nuôi dải nhãn theo tần số (`AiAnnotationStrip`).

## 3. `tcp://127.0.0.1:5555` — AI Detection Review (detector → backend, có ảnh)

- **Bind bởi (PUB):** `tools/yolo_detection.py`, tham số `--review-publish` (mặc định `tcp://127.0.0.1:5555`), tốc độ giới hạn bởi `--review-publish-fps` (mặc định 5 fps, vì payload nặng hơn kênh JSON).
- **Connect bởi (SUB):** `backend/ai_detection_review.py` (`AiDetectionReviewSubscriber`), qua `backend/api/service.py`, cấu hình endpoint bằng `AI_DETECTION_REVIEW_SUB_URL` (mặc định `tcp://127.0.0.1:5555`), bật bằng `AI_DETECTION_REVIEW_SUB_ENABLED`.
- **Nội dung:** multipart 3 phần `[JSON metadata, raw JPEG, annotated JPEG]`:
  - JSON: `sequence`, `timestamp_ns`, `generated_at`, `width`, `height`, `center/start/stop_frequency_hz`, `content_type: "image/jpeg"`, `detections`, `label_freq_ranges_hz` (cùng cấu trúc như mục 2).
  - Phần 2: ảnh gốc (trước khi vẽ box), JPEG quality 90.
  - Phần 3: ảnh đã annotate (có box + nhãn), JPEG quality 90.
- **Giới hạn ở backend:** `MAX_METADATA_BYTES = 256 * 1024`, `MAX_IMAGE_BYTES = 3 * 1024 * 1024` mỗi ảnh, yêu cầu magic bytes JPEG (`backend/ai_detection_review.py`).
- **Mục đích:** nuôi panel "KẾT QUẢ PHÁT HIỆN AI" trên giao diện (ảnh annotate hiển thị qua `GET /api/analyzer/ai/review/status` + `/image`) và nút **Lưu kết quả**, hoạt động dạng bật/tắt liên tục (không phải lưu 1 lần):
  - `POST /api/analyzer/ai/review/save/start` — bật; mỗi snapshot mới nhận từ cổng 5555 sau đó sẽ tự động được ghi ra đĩa cho tới khi dừng.
  - `POST /api/analyzer/ai/review/save/stop` — tắt.
  - `GET /api/analyzer/ai/review/save/status` — `{active, saved_count, last_saved_path, last_error}`, dùng để frontend poll hiển thị trạng thái/số lượng đã lưu.
  - Mỗi lần lưu ghi ra `data/ai_detect/saved/{images,annotated,labels}/<stem>.*` + `<stem>.json` (xem `AI_DETECTION_SAVE_ROOT`). Việc ghi chạy trong thread pool riêng (`asyncio.to_thread`), không chặn subscriber hay các request preview khác.

## 4. `http(s)://127.0.0.1:8000` — Backend HTTP/WebSocket API

- **Chạy bởi:** `python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` (xem `README.md`).
- **Nội dung:** REST API điều khiển thiết bị SAN-90/simulator + WebSocket stream nhị phân theo `backend/api/protocol.py`, các message type:
  | Mã | Ý nghĩa |
  |----|---------|
  | `0x01` | `MESSAGE_SPECTRUM` — phổ tần tức thời |
  | `0x02` | `MESSAGE_SPECTRUM_TEMPORAL` — phổ tần kèm tích luỹ cực đại theo thời gian |
  | `0x03` | `MESSAGE_WATERFALL` — batch dòng waterfall |
  | `0x10` | `MESSAGE_STATUS` — trạng thái thiết bị/backend |
  | `0x11` | `MESSAGE_AI_DETECTIONS` — kết quả AI detect (nhận từ port 5558, forward cho client) |
  | `0x12` | `MESSAGE_ERROR` — lỗi |
  - REST liên quan tới AI review (mục 3): `GET /api/analyzer/ai/review/status`, `GET /api/analyzer/ai/review/image?sequence=&variant=raw|annotated`, `POST /api/analyzer/ai/review/save/start`, `POST /api/analyzer/ai/review/save/stop`, `GET /api/analyzer/ai/review/save/status`.
- **Mục đích:** giao tiếp giữa backend và giao diện web (điều khiển máy phân tích phổ, nhận waterfall/spectrum realtime, nhận kết quả AI detect).

## Sơ đồ luồng dữ liệu tổng quát

```
SAN-90 / Simulator
      │
      ▼
backend (image_publisher) ──PUSH:5557──► tools/yolo_detection.py
      │                                        │
      │                                        ├──PUB:5558 (detections JSON)──► AiDetectionSubscriber ──WebSocket:8000──► AiAnnotationStrip
      │                                        │
      │                                        └──PUB:5555 (metadata + raw/annotated JPEG)──► AiDetectionReviewSubscriber
      │                                                                                              │
      │                                                                          GET /api/analyzer/ai/review/{status,image}
      │                                                                          POST .../save/{start,stop}, GET .../save/status
      │                                                                                              │
      └──────────────────────────────────────────────────────────────────────────────────► panel "KẾT QUẢ PHÁT HIỆN AI" (client web)
```
