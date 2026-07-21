# Ảnh đầu vào của mô hình YOLO

Tài liệu này mô tả chính xác ảnh mà pipeline tạo ra và đưa vào YOLO để detect, dựa
trên code hiện tại của [san90_stream_manager.py](../san90_stream_manager.py) và
[san90_capture.py](../san90_capture.py).

## 1. Bản chất ảnh: waterfall spectrogram

Ảnh **không phải** ảnh chụp camera mà là một **waterfall/spectrogram** dựng từ dữ
liệu phổ (RTA - Real-Time Analyzer) do thiết bị Harogic SAN-90 trả về:

- **Trục ngang (X)** = tần số, trải từ `StartFrequency_Hz` đến `StopFrequency_Hz`
  quanh tần số trung tâm `CENTER_MHZ` (băng thông cố định theo phần cứng, không do
  `SPAN_MHZ` quyết định — field đó chỉ để hiển thị).
- **Trục dọc (Y)** = thời gian, mỗi hàng pixel là một "sweep"/frame phổ chụp tại
  một thời điểm; hàng trên cùng là frame cũ nhất, hàng dưới cùng là frame mới nhất
  trong cửa sổ tích luỹ.
- **Độ sáng mỗi pixel** = mức công suất tín hiệu (dBm) tại (tần số, thời điểm) đó,
  ánh xạ qua colormap thang xám.

Nói cách khác: đây là ảnh "thời gian chồng tần số", mô hình học để nhận diện các
vệt/hoa văn đặc trưng của từng loại tín hiệu (dạng dải rộng liên tục, dạng nhảy
tần rời rạc, nhiễu nền...) thay vì học vật thể trong ảnh chụp thông thường.

## 2. Kích thước & tham số mặc định

Từ `DEFAULT_CONFIG` trong [san90_stream_manager.py](../san90_stream_manager.py):

| Tham số | Giá trị mặc định | Ý nghĩa |
|---|---|---|
| `WIDTH` | 640 px | số cột ảnh = số điểm tần số sau khi resize |
| `HEIGHT` | 640 px | số hàng ảnh = số frame phổ tích luỹ theo thời gian |
| `NUM_FRAMES` | 640 | số frame RTA capture cho mỗi ảnh (= HEIGHT khi không đổi) |
| `CENTER_MHZ` | 2440.0 MHz | tần số trung tâm quét |
| `DECIMATE` | 1 | hệ số decimate của thiết bị |
| `POWER_MIN_DBM` | -130.0 dBm | cận dưới thang màu (đen) |
| `POWER_MAX_DBM` | -50.0 dBm | cận trên thang màu (trắng) |
| `REF_LEVEL_DBM` | -10.0 dBm | mức tham chiếu máy thu |
| `GAIN_STRATEGY` | `low-noise` | chiến lược gain (ưu tiên nhiễu thấp) |
| `PREAMP` | `auto` | tiền khuếch đại tự động |
| colormap | `grey` | ảnh xám (đường live dùng cố định "grey") |

Ảnh xuất ra là **RGB 640×640** (dù là ảnh xám, vẫn lưu 3 kênh bằng nhau R=G=B).
Các tham số này có thể chỉnh khi đang stream qua `update_config()` (đổi tần số,
gain... sẽ gọi lại `RTA_Configuration`; đổi `WIDTH`/`HEIGHT` sẽ cấp lại buffer).

## 3. Cách dựng ảnh — từng bước

### Bước 1: Lấy dữ liệu thô từ thiết bị
`RTA_GetRealTimeSpectrum` ([san90_stream_manager.py:360-368](../san90_stream_manager.py#L360-L368))
được gọi lặp lại; mỗi lần trả về một "packet" gồm:
- `packet_frame` hàng phổ (mỗi hàng = 1 frame theo thời gian),
- mỗi hàng có `frame_width` điểm tần số, kiểu `uint8` (giá trị thô chưa phải dBm),
- `plot_info.ScaleTodBm` / `plot_info.OffsetTodBm`: hệ số đổi thô → dBm thực.

### Bước 2: Đổi sang dBm và ghi vào ma trận waterfall
Hàm `fill_rows_from_packet_np`
([san90_capture.py:150-180](../san90_capture.py#L150-L180)):
1. Đọc khối byte thô thành mảng NumPy `(n_rows, frame_width)`.
2. Đổi hàng loạt sang dBm: `dbm = raw * scale + offset`.
3. Nếu `frame_width == WIDTH`: ghi thẳng vào ma trận `waterfall` (shape
   `HEIGHT × WIDTH`, khởi tạo toàn bộ bằng `POWER_MIN_DBM`) tại các hàng
   `captured … captured+n_rows`.
4. Nếu `frame_width != WIDTH`: nội suy tuyến tính theo trục tần số bằng
   `np.interp` để resize mỗi hàng về đúng `WIDTH` cột.

Quá trình lặp lại cho tới khi đủ `NUM_FRAMES` hàng (mặc định bằng `HEIGHT`) →
ma trận `waterfall` lúc này chứa toàn bộ giá trị dBm cho một "khung" ảnh.

### Bước 3: Ánh xạ dBm → màu (colormap)
Hàm `waterfall_to_rgb`
([san90_capture.py:141-148](../san90_capture.py#L141-L148)):
1. Clip giá trị dBm về `[POWER_MIN_DBM, POWER_MAX_DBM]`.
2. Chuẩn hoá tuyến tính sang chỉ số nguyên `0–255`
   (`idx = (dbm - POWER_MIN_DBM) * 255 / (POWER_MAX_DBM - POWER_MIN_DBM)`).
3. Tra bảng màu (LUT) — mặc định `grey` (`(i, i, i)` cho mọi `i`) — vector hoá
   toàn bộ mảng bằng NumPy, ra chuỗi bytes RGB.

Công suất càng cao (gần `POWER_MAX_DBM`) → pixel càng sáng; công suất càng thấp
(gần `POWER_MIN_DBM`, tức nền nhiễu) → pixel càng tối.

### Bước 4: Dựng ảnh PIL
([san90_stream_manager.py:383-384](../san90_stream_manager.py#L383-L384))
```python
rgb_bytes = waterfall_to_rgb(waterfall, POWER_MIN_DBM, POWER_MAX_DBM, "grey")
base_img = Image.frombytes("RGB", (width, height), rgb_bytes)
```
`base_img` (640×640 RGB) là ảnh **gốc**, chính là input đưa cho model — không qua
bất kỳ bước tiền xử lý (crop, normalize thủ công, augment...) nào khác trước khi
gọi YOLO; việc resize/letterbox theo input size mạng là do Ultralytics tự xử lý
nội bộ khi `predict()`.

## 4. Đưa vào model detect

([ai_model.py:67-69](../ai_model.py#L67-L69))
```python
result = model.predict(pil_img, conf=0.25)[0]
```
- Weight đang dùng: `runs/detect/runs/detect/finetune_captured-2/weights/best.pt`
  ([ai_model.py:27](../ai_model.py#L27)), tự reload nếu có bản mới hơn.
- Ngưỡng confidence mặc định: `0.25`.
- Model trả về danh sách box (`xyxy` theo toạ độ pixel trên ảnh 640×640) +
  `class_id`/`class_name`/`confidence` cho từng box.

## 5. Tập lớp (classes)

Theo [yolo_dataset/data.yaml](../yolo_dataset/data.yaml) (9 lớp dùng để train):

```
FR_SKY, NOISE, ELRS, LRVTX, DJI_20MHz, DJI_40MHz, AVTX, DATALINK, DJI_10MHz
```

> Lưu ý: [data/classes.txt](../data/classes.txt) liệt kê thêm `TBS` (10 lớp) nhưng
> `data.yaml` — cấu hình thực tế dùng để train — chỉ có 9 lớp trên. Bảng màu
> annotate trong [ai_model.py:112-116](../ai_model.py#L112-L116) (`WIDEBAND`,
> `FHSS`, `NOISE`) cũng dùng tên nhóm khác với `classes.txt`/`data.yaml`; nếu cần
> annotate đúng màu theo từng lớp thật, bảng màu này nên được cập nhật lại.

## 6. Lưu kèm (khi bật `save_enabled`)

Khi cấu hình `save_enabled=True`, `detect_save.save_result()`
([detect_save.py](../detect_save.py)) lưu 3 thứ cho mỗi ảnh có detection, cùng
`stem` (tên file):
- `images/<stem>.jpg`: ảnh waterfall gốc (chưa vẽ box) — dùng làm ảnh train YOLO.
- `annotated/<stem>.jpg`: ảnh có vẽ bounding box + nhãn (để xem/kiểm tra bằng mắt).
- `labels/<stem>.txt`: nhãn theo format YOLO (`class_id cx cy w h`, toạ độ đã
  chuẩn hoá theo `width`/`height` của ảnh gốc).

## 7. Tóm tắt luồng dữ liệu

```
RTA power samples (uint8, theo từng frame)
        │  scale/offset → dBm
        ▼
Ma trận waterfall (HEIGHT × WIDTH, float32 dBm)
        │  clip + chuẩn hoá [POWER_MIN_DBM, POWER_MAX_DBM] → [0,255]
        ▼
Ảnh xám RGB 640×640 (PIL.Image)
        │  YOLO.predict(conf=0.25)
        ▼
Danh sách detection: class_id, class_name, confidence, box(xyxy)
```
