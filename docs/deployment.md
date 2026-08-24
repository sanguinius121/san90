# Triển khai SAN-90 Spectrum Console sang máy mới

Tài liệu này mô tả các bước triển khai toàn bộ hệ thống (backend + AI
detector + frontend) sang một máy tính khác, dựa trên kiến trúc hiện tại:
**chỉ cần khởi động backend, mọi dịch vụ còn lại tự chạy theo.**

## 1. Kiến trúc hiện tại

Kể từ khi tích hợp, `python3 -m uvicorn backend.main:app` (chạy qua
`npm run backend:start`) tự spawn 2 tiến trình con trong vòng đời của nó
(`backend/main.py` → `lifespan`):

| Tiến trình con | Module quản lý | Vai trò |
|---|---|---|
| `tools/yolo_detection.py` | [`backend/ai_detector_process.py`](../backend/ai_detector_process.py) | Nhận ảnh GRAY8 (port 5557), chạy YOLO, publish kết quả (5558) + ảnh review (5555) |
| Vite dev server (frontend) | [`backend/frontend_process.py`](../backend/frontend_process.py) | Serve giao diện web tại port 5173 |

Cả hai được start/stop cùng lúc với backend, dùng chung tiến trình Python
(`sys.executable`) cho AI detector — **vì vậy các thư viện AI (opencv,
ultralytics) phải được cài trong cùng môi trường Python với backend**, không
còn là "venv riêng" như tài liệu cũ.

Sơ đồ cổng: xem [ports.md](ports.md).

## 2. Yêu cầu hệ thống

- Ubuntu 22.04/24.04 x86-64 (hoặc tương đương)
- Python 3.10+ (đã test với 3.10.12)
- Node.js **20.19 trở lên** (dự án đang dùng 24.x qua nvm)
- PostgreSQL (tuỳ chọn — chỉ cần nếu bật lưu ảnh detect vào DB, xem mục 7)
- Thiết bị SAN-90 thật (USB ID `367f:0001`) nếu không dùng simulator

## 3. Lấy mã nguồn

```bash
git clone <repo-url> san90
cd san90
```

**Lưu ý — các thứ KHÔNG nằm trong git, phải copy thủ công từ máy cũ:**

| Đường dẫn | Vì sao | Cách copy |
|---|---|---|
| `ai_detect/weights/best.pt`, `last.pt`, `best_openvino_model/` (~200MB) | Không track git (`git status` báo `??`) | `rsync -a` hoặc `scp -r` từ máy cũ |
| `data/` (nếu muốn giữ lịch sử detect/preview đã lưu) | Runtime-only, không track git | Tuỳ chọn |

`harogic/` (SDK + udev rules HAROGIC) **có** trong git, không cần copy riêng.

## 4. Cài Node.js (nếu bản có sẵn cũ hơn 20.19)

```bash
node_version=v24.18.0
node_archive="node-${node_version}-linux-x64.tar.xz"
wget -q "https://nodejs.org/dist/${node_version}/${node_archive}"
mkdir -p ~/.local/opt ~/.local/bin
tar -xJf "${node_archive}" -C ~/.local/opt
ln -sfn ~/.local/opt/node-${node_version}-linux-x64/bin/node ~/.local/bin/node
ln -sfn ~/.local/opt/node-${node_version}-linux-x64/bin/npm  ~/.local/bin/npm
export PATH="$HOME/.local/bin:$PATH"
node --version
```

Chi tiết đầy đủ (checksum verify, v.v.): [dependency-installation.md](dependency-installation.md).

## 5. Cài dependency Python (backend + AI detector, chung 1 môi trường)

```bash
python3 -m pip install --user --break-system-packages -r backend/requirements.txt
```

`backend/requirements.txt` giờ đã gồm cả `opencv-python` và `ultralytics`
(dùng chung cho AI detector được backend spawn), cộng `psycopg2-binary` (cho
tính năng lưu ảnh detect vào Postgres).

Nếu chưa có model OpenVINO (chỉ cần 1 lần, sau khi đã copy `best.pt`):

```bash
python3 -c "from ultralytics import YOLO; YOLO('ai_detect/weights/best.pt').export(format='openvino')"
```

## 6. Cài dependency Node (frontend)

```bash
npm ci
```

Cần chạy bước này **kể cả khi chỉ chạy backend**, vì backend tự gọi thẳng
`node_modules/.bin/vite` để serve frontend.

## 7. Cài đặt phần cứng USB

### 7.1. HAROGIC SAN-90 (bắt buộc nếu dùng thiết bị thật)

```bash
sudo install -o root -g root -m 0644 \
  harogic/Linux_API/htraapi/configs/htra-cyusb.rules \
  /etc/udev/rules.d/htra-cyusb.rules
sudo install -o root -g root -m 0644 \
  harogic/Linux_API/htraapi/configs/htrausb.conf \
  /etc/htrausb.conf
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=367f --action=add
udevadm settle

lsusb -d 367f:0001   # phải thấy đúng 1 thiết bị
```

### 7.2. `usbreset` (cần cho quy trình start/stop an toàn)

```bash
sudo apt install -y build-essential usbutils
wget -q https://raw.githubusercontent.com/gregkh/usbutils/8fb7ed457876db9770ef0c4067155866faffcca9/usbreset.c
gcc -O2 -o usbreset usbreset.c
install -m 0755 usbreset ~/.local/bin/usbreset
```

### 7.3. FT232H RF switch (tuỳ chọn)

Xem [ft232h-rf-switch.md](ft232h-rf-switch.md). Nếu không có phần cứng này,
đặt `SAN90_RF_SWITCH_ENABLED=false` — hệ thống vẫn chạy bình thường, chỉ log
cảnh báo reconnect liên tục nếu để mặc định `true` mà không có thiết bị.

## 8. (Tuỳ chọn) PostgreSQL cho lưu ảnh detect

Tính năng lưu ảnh annotated vào bảng `spectrogram` (xem
[`backend/ai_detection_db.py`](../backend/ai_detection_db.py)) **tự tắt êm**
nếu không kết nối được DB (log cảnh báo, không crash backend). Nếu muốn bật:

1. Có sẵn Postgres với DB (mặc định code trỏ tới `uavdetection`) và bảng
   `spectrogram` (cột: `receiver_id, source, sequence, captured_at,
   center_freq_hz, start_freq_hz, stop_freq_hz, image_png, ...` — xem chi
   tiết trong `ai_detection_db.py`).
2. Set `AI_DETECTION_DB_DSN` nếu khác mặc định
   `postgresql://postgres:123456@localhost:5432/uavdetection`.
3. Set `AI_DETECTION_DB_RECEIVER_ID` khớp với `receiver_id` của máy SAN-90
   trong bảng `receiver` (mặc định `2`).
4. Không cần DB thì set `AI_DETECTION_DB_ENABLED=false`.

## 9. Biến môi trường quan trọng

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ANALYZER_SOURCE` | (đặt qua tham số `npm run backend:start[:simulator]`) | `san90` (thật) hoặc `simulator` |
| `SAN90_RF_SWITCH_ENABLED` | `true` | Tắt nếu không có FT232H |
| `AI_DETECTOR_ENABLED` | `true` | Tắt nếu không muốn backend tự chạy AI detector |
| `AI_DETECTOR_MODEL` | `ai_detect/weights/best_openvino_model` | Đường dẫn model YOLO |
| `AI_DETECTOR_CONF` | `0.5` | Ngưỡng confidence |
| `FRONTEND_ENABLED` | `true` | Tắt nếu muốn tự chạy frontend riêng (`npm run frontend:start`) |
| `FRONTEND_HOST` / `FRONTEND_PORT` | `0.0.0.0` / `5173` | Địa chỉ frontend dev server |
| `AI_DETECTION_DB_ENABLED` | `true` | Tắt nếu không dùng Postgres |
| `AI_DETECTION_DB_DSN` | `postgresql://postgres:123456@localhost:5432/uavdetection` | Chuỗi kết nối DB |
| `AI_DETECTION_DB_RECEIVER_ID` | `2` | `receiver_id` gán cho các bản ghi lưu |
| `SAN90_USB_HANDOFF_RESET` | `1` | Đặt `0` để tắt auto USB reset khi start/stop (dùng khi debug) |

Đặt biến môi trường trước lệnh `npm run backend:start`, ví dụ:

```bash
AI_DETECTOR_ENABLED=false npm run backend:start:simulator
```

## 10. Khởi động

```bash
# Thiết bị SAN-90 thật (kèm AI detector + frontend tự động)
npm run backend:start

# Hoặc dùng simulator, không cần phần cứng
npm run backend:start:simulator
```

Một lệnh duy nhất là đủ — không cần chạy `tools/yolo_detection.py` hay
`npm run frontend:start` riêng nữa (2 lệnh đó vẫn còn, dùng khi cần chạy
tách biệt để debug).

## 11. Kiểm tra hoạt động

```bash
npm run services:status
curl -s http://127.0.0.1:8000/api/analyzer/status | head -c 200
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5173/
```

Mở trình duyệt: `http://<ip-máy>:5173` (hoặc `?source=simulator` /
`?source=san90` để chọn nguồn).

Log:
- `.run/backend.log` — backend + cảnh báo RF switch/AI
- `.run/ai_detector.log` — YOLO detector (model load, detection theo frame)
- `.run/frontend.log` — Vite dev server

## 12. Dừng

```bash
npm run backend:stop
```

Lệnh này tự dừng AI detector + frontend con, sau đó thực hiện USB handoff
reset an toàn cho SAN-90.

## 13. Xử lý sự cố thường gặp

| Triệu chứng | Nguyên nhân thường gặp | Cách kiểm tra |
|---|---|---|
| `npm run backend:start` thoát ngay, không log gì | `lsusb -d 367f:0001` không thấy thiết bị → script reset USB fail | `lsusb -d 367f:0001`; cắm lại cáp/nguồn SAN-90 |
| UI báo `NetworkError when attempting to fetch resource` | Backend chưa chạy, hoặc frontend mở bằng hostname không nằm trong CORS allowlist (`backend/main.py`) | `curl http://127.0.0.1:8000/api/analyzer/status`; mở UI qua `localhost`/`127.0.0.1` |
| Không thấy nhãn tần số trên waterfall | AI detector chưa chạy, hoặc model thiếu | `tail .run/ai_detector.log`; kiểm tra `ai_detect/weights/best_openvino_model` tồn tại |
| `.run/ai_detector.log` báo `ModuleNotFoundError: ultralytics`/`cv2` | Thiếu dependency trong đúng môi trường Python mà backend dùng (`sys.executable`) | Chạy lại bước 5 với đúng `python3` mà `uvicorn` sẽ dùng |
| `Address already in use` cổng 5558/5555/5173/8000 | Có tiến trình cũ chưa dừng sạch (chạy tay hoặc từ phiên trước) | `ps aux \| grep -E "yolo_detection\|vite\|uvicorn"`; dừng bằng `npm run backend:stop` trước khi start lại |
| Lưu ảnh detect vào DB không hoạt động | Postgres chưa chạy / DSN sai / bảng `spectrogram` chưa tồn tại | `curl http://127.0.0.1:8000/api/analyzer/ai/review/db/status` xem `last_error` |
