# Chạy toàn bộ service (Web + AI)

> **Đã lỗi thời kể từ khi tích hợp AI detector + frontend vào backend.**
> Giờ chỉ cần `npm run backend:start` (hoặc `:simulator`) — xem
> [docs/deployment.md](docs/deployment.md). Tài liệu dưới đây chỉ còn hữu
> ích khi cần chạy từng dịch vụ tách biệt để debug.

Có 3 tiến trình độc lập cần chạy: **backend**, **frontend**, và **AI detector**
(`tools/yolo_detection.py`). AI detector không nằm trong
`scripts/manage-services.sh`, phải tự chạy riêng.

## 1. Cài đặt (một lần)

```bash
# Backend
pip install -r backend/requirements.txt

# Frontend
npm install

# AI detector
pip install opencv-python ultralytics pyzmq

# Nếu chưa có model OpenVINO (chỉ cần làm 1 lần)
python3 -c "from ultralytics import YOLO; YOLO('ai_detect/weights/best.pt').export(format='openvino')"
```

## 2. Chạy backend (port 8000)

```bash
npm run backend:start:simulator   # nguồn dữ liệu giả lập, không cần phần cứng
# hoặc
npm run backend:start             # nguồn dữ liệu từ thiết bị SAN-90 thật
```

Log: `.run/backend.log`. Dừng bằng `npm run backend:stop`.

## 3. Chạy AI detector

```bash
python3 tools/yolo_detection.py \
  --connect tcp://127.0.0.1:5557 \
  --model ai_detect/weights/best_openvino_model \
  --publish tcp://127.0.0.1:5558 \
  --review-publish tcp://127.0.0.1:5555
```

- `--publish` (5558): kết quả detect dạng JSON nhẹ, nuôi dải nhãn theo tần số trên UI.
- `--review-publish` (5555): kèm ảnh gốc + ảnh annotate, nuôi panel "KẾT QUẢ PHÁT HIỆN AI" và nút Lưu kết quả.

Chạy sau khi backend đã lên (backend bind port 5557 để detector kết nối vào).

## 4. Chạy frontend (port 5173)

```bash
npm run frontend:start
# hoặc, khi đang dev:
npm run dev
```

Log (nếu dùng `frontend:start`): `.run/frontend.log`. Dừng bằng `npm run frontend:stop`.

## 5. Mở giao diện

Truy cập `http://localhost:5173`.

## 6. Kiểm tra / dừng

```bash
npm run services:status   # trạng thái backend + frontend (không bao gồm AI detector)
npm run backend:stop
npm run frontend:stop
```

AI detector dừng bằng `Ctrl+C` trong terminal đang chạy nó (hoặc `kill` theo PID).

## Thứ tự khởi động khuyến nghị

1. Backend (bind cổng 5557/5558/5555, mở port 8000)
2. AI detector (kết nối vào 5557, publish 5558 + 5555)
3. Frontend (gọi API/WebSocket vào port 8000)

Chi tiết vai trò từng cổng: xem [docs/ports.md](docs/ports.md).
