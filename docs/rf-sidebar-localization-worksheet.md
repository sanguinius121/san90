# Phiếu chuẩn bị Việt hóa sidebar RF

Tài liệu này thống kê các thuật ngữ và chuỗi giao diện hiện có trong sidebar
`CÀI ĐẶT THAM SỐ` (tab `RF`). Thứ tự các nhóm bám theo thứ tự section trên UI.

Mỗi mục giữ nguyên chuỗi nguồn trong dấu backtick. Điền nội dung mong muốn sau hai
dòng `Việt hóa thuật ngữ` và `Gợi ý`. Không sửa chuỗi nguồn để sau này còn đối
chiếu chính xác với code và test.

Tên tệp ghi, đường dẫn do người dùng nhập, lỗi do backend/SDK trả về và nhãn RF
path nhận động từ capability không thể liệt kê cố định. Các mẫu và fallback hiện
có được ghi riêng ở cuối tài liệu.

## 1. Header của sidebar

### `CÀI ĐẶT THAM SỐ`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Đặt lại bố cục`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Đặt lại chiều rộng bảng điều khiển`

- Việt hóa thuật ngữ:
- Gợi ý:

### `TRỰC TUYẾN`

- Việt hóa thuật ngữ:
- Gợi ý:

### `RECONFIGURING`

- Việt hóa thuật ngữ:
- Gợi ý:

### `PLAYBACK`

- Việt hóa thuật ngữ: PHÁT LẠI
- Gợi ý: Phát lại dữ liệu phổ đã ghi từ trước

## 2. Section `Frequency`

### `Frequency`

- Việt hóa thuật ngữ: CÀI ĐẶT TẦN SỐ
- Gợi ý: Cài đặt tần số trung tâm và bước tần

### `Center frequency`

- Việt hóa thuật ngữ: Tần số trung tâm
- Gợi ý: Cài đặt tần số trung tâm của thiết bị. Đơn vị MHz hoặc GHz. Ví dụ 2440 MHz

### `Step frequency`

- Việt hóa thuật ngữ: Bước tần
- Gợi ý: Cài đặt bước tần của tần số trung tâm. Đơn vị MHz hoặc GHZ. Ví dụ 10 MHz

### `GHz`

- Việt hóa thuật ngữ:
- Gợi ý:

### `MHz`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Center frequency must be between {minimum} Hz and {maximum} Hz`

- Việt hóa thuật ngữ: Tần số trung tâm phải lớn hơn {minimum} Hz và nhỏ hơn {minimum} Hz
- Gợi ý:

## 3. Section `Frequency Scan`

### `Frequency Scan`

- Việt hóa thuật ngữ: QUÉT TẦN SỐ
- Gợi ý: Quét tần số theo các tần số trung tâm đã cài đặt trước

### `Scanning {current}/{total}`

- Việt hóa thuật ngữ: ĐANG QUÉT
- Gợi ý:

### `TUNING`

- Việt hóa thuật ngữ: Đang cài đặt
- Gợi ý:

### `DWELLING`

- Việt hóa thuật ngữ:
- Gợi ý:

### `STOPPING`

- Việt hóa thuật ngữ: ĐANG DỪNG
- Gợi ý:

### `ERROR`

- Việt hóa thuật ngữ: LỖI
- Gợi ý:

### `DELETE`

- Việt hóa thuật ngữ: XÓA
- Gợi ý:

### `Step`

- Việt hóa thuật ngữ: BƯỚC TẦN
- Gợi ý: Cài đặt bước tần của tần số trung tâm. Đơn vị MHz hoặc GHZ. Ví dụ 10 MHz

### `Duration`

- Việt hóa thuật ngữ: THỜI GIAN
- Gợi ý: Thời gian quét của tần số này 

### `+ Add frequency`

- Việt hóa thuật ngữ: + THÊM TẦN SỐ
- Gợi ý:

### `Start scan`

- Việt hóa thuật ngữ: BẮT ĐẦU QUÉT
- Gợi ý: 

### `Stop scan`

- Việt hóa thuật ngữ: DỪNG 
- Gợi ý:

### `Dwell ≥ {seconds}s · default step 10 MHz`

- Việt hóa thuật ngữ: Thời gian ≥ {seconds}s · Bước tần mặc định 10 MHz
- Gợi ý:

### `Scan {index} enabled`

- Việt hóa thuật ngữ:
- Gợi ý: Kích hoạt tần số này

### `Delete scan {index}`

- Việt hóa thuật ngữ:
- Gợi ý: Vô hiệu hóa tần số này

### `Scan {index} center frequency`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Scan {index} frequency unit`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Decrease scan {index} frequency`

- Việt hóa thuật ngữ:
- Gợi ý: Giảm tần số

### `Increase scan {index} frequency`

- Việt hóa thuật ngữ:
- Gợi ý: Tăng tần số

### `Scan {index} step`

- Việt hóa thuật ngữ: Bước tần
- Gợi ý: 

### `Scan {index} step unit`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Scan {index} duration`

- Việt hóa thuật ngữ: Thời gian
- Gợi ý: 

### `Enter valid frequencies, positive steps, and dwell durations.`

- Việt hóa thuật ngữ: Nhập tần số, bước tần và thời gian đúng định dạng
- Gợi ý: Tần số trong khoảng 50 MHz đến 9000 MHz, bước tần không âm, thời gian > 0.5s

### `Frequency, step, or duration is outside the supported range.`

- Việt hóa thuật ngữ: Tần số, bước tần và thời gian không được hỗ trợ
- Gợi ý:

### `Each scan frequency must be within the analyzer frequency range.`

- Việt hóa thuật ngữ: Các tần số quét phải được hỗ trợ bởi thiết bị
- Gợi ý:

### `Step must be positive and no larger than the supported tuning range.`

- Việt hóa thuật ngữ: Bước tần phải là số dương và không lớn hơn tần số hỗ trợ bởi thiết bị
- Gợi ý:

### `Enter a valid frequency, step, and duration before applying the step.`

- Việt hóa thuật ngữ: Nhập tần số, bước tần và thời gian đúng định dạng
- Gợi ý:

### `The requested step would exceed the analyzer frequency range.`

- Việt hóa thuật ngữ: Bước tần đang lớn hơn tần số được thiết bị hỗ trợ
- Gợi ý:

### `Enable at least one valid frequency and enter valid steps and dwell durations.`

- Việt hóa thuật ngữ: Nhập ít nhất một tần số và thời gian phù hợp
- Gợi ý:

### `Unable to save frequency scan`

- Việt hóa thuật ngữ: "Không thể lưu tần số:
- Gợi ý:

### `Unable to start frequency scan`

- Việt hóa thuật ngữ: "Không thể bắt đầu quét"
- Gợi ý:

### `Unable to stop frequency scan`

- Việt hóa thuật ngữ: "Không thể dừng quét"
- Gợi ý:

## 4. Section `RF Path`

### `RF Path`

- Việt hóa thuật ngữ: CÀI ĐẶT RF
- Gợi ý: Lựa chọn tuyến cao tần

### `RF input path`

- Việt hóa thuật ngữ: Tuyến cao tần
- Gợi ý: Lựa chọn tuyến cao tần cho thiết bị

### `Requested`

- Việt hóa thuật ngữ: Yêu cầu
- Gợi ý: Người dùng yêu cầu tuyến RF này

### `Hardware`

- Việt hóa thuật ngữ: Hiện tại
- Gợi ý: Phần cứng hiện đang kết nối với RF này

### `GPIO`

- Việt hóa thuật ngữ:
- Gợi ý: Giá trị của GPIO

### `UNKNOWN`

- Việt hóa thuật ngữ: "Không rõ trạng thái"
- Gợi ý:

### `SIMULATED`

- Việt hóa thuật ngữ: "Giả lập"
- Gợi ý:

### `FT232H CONNECTED`

- Việt hóa thuật ngữ: "Đã kết nối FT232H"
- Gợi ý:

### `RECONNECTING · {attempts}`

- Việt hóa thuật ngữ: "Đang thử kết nối lại · {attempts}
- Gợi ý:

### `EXTERNAL LNA ACTIVE`

- Việt hóa thuật ngữ: LNA 2.4/5.8 GHz đang được kết nối
- Gợi ý:

### `RF1 — 2.4/5.8 GHz LNA`

- Việt hóa thuật ngữ:
- Gợi ý:

### `RF2…RF7 — Auxiliary`

- Việt hóa thuật ngữ: RF2…RF7 — Dự phòng
- Gợi ý:

### `RF8 — Wideband antenna`

- Việt hóa thuật ngữ: RF8 — Ăng ten băng rộng
- Gợi ý:

### `External 2.4/5.8 GHz LNA path selected. Monitor receiver overload when strong nearby signals are present.`

- Việt hóa thuật ngữ: LƯU Ý!! LNA 2.4/5.8 GHz đang được kích hoạt, chú ý giảm Mức tham chiếu và tắt Pream khi ở gần nguồn tín hiệu mạnh. Chú ý cảnh báo overload của thiết bị 
- Gợi ý:

### `Requested path is not verified by GPIO readback.`

- Việt hóa thuật ngữ: Tuyến RF đang không được xác nhận bởi chuyển mạch
- Gợi ý:

### `The FT232H and externally powered RF switch are disconnected. RF path is unknown.`

- Việt hóa thuật ngữ: FT232H đang bị ngắt kết nối. Tuyến RF đang không xác định
- Gợi ý:

### `FT232H communication is unavailable. RF8 is the expected pull-up fail-safe path, but it is not verified.`

- Việt hóa thuật ngữ: FT232H đang không có sẵn, RF8 đang được kết nối nhưng không được xác nhận bởi phần cứng. Lưu ý khi sử dụng
- Gợi ý:

### `RF switch status unavailable`

- Việt hóa thuật ngữ: Trạng thái chuyển mạch đang không có sẵn
- Gợi ý:

### `RF path change failed`

- Việt hóa thuật ngữ: Thay đổi chuyển mạch thất bại
- Gợi ý:

## 5. Section `Amplitude`

### `Amplitude`

- Việt hóa thuật ngữ: CÀI ĐẶT BIÊN ĐỘ
- Gợi ý:

### `Reference level`

- Việt hóa thuật ngữ: Mức tham chiếu
- Gợi ý: Lựa chọn mức tham chiếu cho thiết bị. Mức tham chiếu là mức level cao nhất hiển thị trên cửa sổ phổ

### `Attenuation mode`

- Việt hóa thuật ngữ: Chế độ suy hao
- Gợi ý: Lựa chọn chế độ suy hao của tín hiệu đầu vào giữa tự động và thủ công. Lưu ý cảnh báo OVERLOAD của thiết bị khi sử dụng

### `Attenuation`

- Việt hóa thuật ngữ: Mức suy hao (dB)
- Gợi ý: Cài đặt mức suy hao cho tín hiệu đầu vào

### `Automatic`

- Việt hóa thuật ngữ: Tự động
- Gợi ý:

### `Manual`

- Việt hóa thuật ngữ: Thủ công
- Gợi ý:

### `Preamplifier`

- Việt hóa thuật ngữ: Tiền khuếch đại
- Gợi ý: Lựa chọn chế độ tiền khuếch đại của thiết bị. Lưu ý khi sử dụng gần nguồn tín hiệu lớn

### `Auto`

- Việt hóa thuật ngữ: Tự động
- Gợi ý:

### `Off`

- Việt hóa thuật ngữ: Tắt
- Gợi ý:

### `Low gain`

- Việt hóa thuật ngữ: Khuếch đại thấp
- Gợi ý:

### `Medium gain`

- Việt hóa thuật ngữ: Khuếch đại vừa
- Gợi ý:

### `High gain`

- Việt hóa thuật ngữ: Khuếch đại lớn
- Gợi ý:

### `Gain strategy`

- Việt hóa thuật ngữ: Cấu hình khuếch đại
- Gợi ý: Cấu hình kiểu khuếch đại cho thiết bị, có thể chọn giữa "Tạp âm thấp" hoặc "Tuyến tính cao"

### `Low noise`

- Việt hóa thuật ngữ: "Tạp âm thấp"
- Gợi ý:

### `High linearity`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Amplitude offset`

- Việt hóa thuật ngữ: 
- Gợi ý: Tăng giảm offset cho thiết bị. Lưu ý thiết bị sẽ hiển thị theo mức offset và có thể không hiển thị đúng mức của tín hiệu

### `IF AGC`

- Việt hóa thuật ngữ: AGC trung tần
- Gợi ý: Trạng thái của AGC trung tần

### `IF AGC target`

- Việt hóa thuật ngữ: Mức bão hòa 
- Gợi ý: Điều chỉnh mức bão hòa của ADC, mức càng lớn thì càng tới gần độ bão hòa của ADC. 

### `IF AGC period mode`

- Việt hóa thuật ngữ: Chế độ chu kỳ AGC
- Gợi ý:

### `One-shot`

- Việt hóa thuật ngữ: Chỉ một lần
- Gợi ý:

### `Dynamic`

- Việt hóa thuật ngữ: Động
- Gợi ý:

### `Periodic`

- Việt hóa thuật ngữ: Chu kỳ
- Gợi ý:

### `One-shot runs once before sampling; Dynamic uses 0 s; Periodic runs at a positive interval.`

- Việt hóa thuật ngữ:
- Gợi ý:

### `IF AGC period`

- Việt hóa thuật ngữ:
- Gợi ý:

### `IF AGC gain`

- Việt hóa thuật ngữ: Khuếch đại trung tần
- Gợi ý: Mức khuếch đại trung tần. Đơn vị dB

### `Decrease IF AGC gain`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Increase IF AGC gain`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Configuration failed`

- Việt hóa thuật ngữ:
- Gợi ý:

### `IF AGC target configuration failed`

- Việt hóa thuật ngữ:
- Gợi ý:

### `IF AGC period configuration failed`

- Việt hóa thuật ngữ:
- Gợi ý:

## 6. Section `Bandwidth`

### `Bandwidth`

- Việt hóa thuật ngữ: BĂNG THÔNG
- Gợi ý: Điều chỉnh băng thông của thiết bị

### `RBW mode`

- Việt hóa thuật ngữ: RBW - Băng thông phân giải
- Gợi ý:

### `Auto`

- Việt hóa thuật ngữ: Tự động
- Gợi ý:

### `Manual`

- Việt hóa thuật ngữ: Thủ công
- Gợi ý:

### `Time/Frequency resolution trade-off`

- Việt hóa thuật ngữ: Trao đổi miền thời gian/tần số
- Gợi ý: Đánh đổi giữa miền thời gian, tần số khi vẽ phổ. Ưu tiên kéo về miền thời gian nếu muốn quan sát các tần số nhảy tần, có thời gian tồn tại ngắn. Ưu tiên kéo về miền tần số nếu muốn tăng hiển thị chọn lọc tần số

### `APPLYING`

- Việt hóa thuật ngữ: Đang áp dụng
- Gợi ý:

### `EXPECTED`

- Việt hóa thuật ngữ: RBW kỳ vọng
- Gợi ý:

### `ACTIVE`

- Việt hóa thuật ngữ: Đã kích hoạt
- Gợi ý:

### `Time`

- Việt hóa thuật ngữ: Thời gian
- Gợi ý:

### `Frequency`

- Việt hóa thuật ngữ: Tần số
- Gợi ý:

### `Requested RBW`

- Việt hóa thuật ngữ: RBW yêu cầu
- Gợi ý:

### `Expected RBW`

- Việt hóa thuật ngữ: RBW kỳ vọng
- Gợi ý:

### `Actual RBW`

- Việt hóa thuật ngữ: RBW thực tế
- Gợi ý:

### `FFT size`

- Việt hóa thuật ngữ: Kích cỡ FFT
- Gợi ý:

### `Spectrum points`

- Việt hóa thuật ngữ: Số điểm phổ
- Gợi ý:

### `Trace rate`

- Việt hóa thuật ngữ: Tốc độ làm mới
- Gợi ý:

### `Spectrum display`

- Việt hóa thuật ngữ: FPS
- Gợi ý:

### `Bin spacing`

- Việt hóa thuật ngữ: Khoảng cách Bin
- Gợi ý:

### `Waterfall`

- Việt hóa thuật ngữ: 
- Gợi ý:

### `Waterfall batch`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Time resolution`

- Việt hóa thuật ngữ: Độ phân giải thời gian
- Gợi ý:

### `Traces / row`

- Việt hóa thuật ngữ: 
- Gợi ý:

### `Visible span`

- Việt hóa thuật ngữ: Độ rộng cửa sổ thời gian
- Gợi ý:

### `CUSTOM RBW`

- Việt hóa thuật ngữ: Tinh chỉnh RBW
- Gợi ý:

### `Advanced numeric RBW`

- Việt hóa thuật ngữ: Tinh chỉnh RBW
- Gợi ý: Thay đổi RBW 

### `RBW request`

- Việt hóa thuật ngữ:
- Gợi ý:

### `VBW`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Window function`

- Việt hóa thuật ngữ: Loại cửa sổ
- Gợi ý: Thay đổi loại cửa sổ theo các mục đích quan sát phổ khác nhau. Nếu không rõ hãy chọn `Blackman–Nuttall`

### `Flat top`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Blackman–Nuttall`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Low sidelobe`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Rectangular`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Kaiser`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Invalid resolution trade-off step`

- Việt hóa thuật ngữ: resolution trade-off step không đúng
- Gợi ý:

### `Trade-off configuration failed`

- Việt hóa thuật ngữ: Thất bại khi áp dụng trade-off
- Gợi ý:

## 7. Section `Detection`

### `Detection`

- Việt hóa thuật ngữ: Chế độ phát hiện công suất
- Gợi ý: Trong máy phân tích phổ (Spectrum Analyzer), chế độ phát hiện công suất hay còn gọi là Detector Mode (chế độ bộ dò) là thuật toán xử lý tín hiệu số dùng để nén và chuyển đổi các mẫu dữ liệu điện áp thu được thành một giá trị điểm ảnh (pixel/bin) hiển thị trên màn hình.

### `Detector mode`

- Việt hóa thuật ngữ: Chế độ phát hiện công suất
- Gợi ý:

### `Sample`

- Việt hóa thuật ngữ: 
- Gợi ý: Lấy mẫu tức thời tại một điểm ngẫu nhiên trong mỗi khoảng.

### `Positive peak`

- Việt hóa thuật ngữ:
- Gợi ý: Lấy giá trị lớn nhất trong mỗi khoảng thời gian/tần số quét.

### `Average`

- Việt hóa thuật ngữ:
- Gợi ý: Lấy giá trị trung bình biên độ để khử nhiễu nền.

### `Negative peak`

- Việt hóa thuật ngữ:
- Gợi ý:

### `RMS`

- Việt hóa thuật ngữ:
- Gợi ý: Tính căn bậc hai trung bình các giá trị điện áp để đo chính xác công suất trung bình thực tế của tín hiệu và nhiễu.

### `Auto peak`

- Việt hóa thuật ngữ:
- Gợi ý:

## 8. Section `Record`

### `Record`

- Việt hóa thuật ngữ: GHI DỮ LIỆU
- Gợi ý:

### `On`

- Việt hóa thuật ngữ: BẬT
- Gợi ý:

### `Off`

- Việt hóa thuật ngữ: TẮT
- Gợi ý:

### `Start recording`

- Việt hóa thuật ngữ: BẮT ĐẦU GHI
- Gợi ý:

### `Stop recording`

- Việt hóa thuật ngữ: DỪNG GHI
- Gợi ý:

### `Record mode`

- Việt hóa thuật ngữ: Chế độ ghi
- Gợi ý:

### `Fixed`

- Việt hóa thuật ngữ: Cố định
- Gợi ý:

### `Manual`

- Việt hóa thuật ngữ: Thủ công
- Gợi ý:

### `Record time`

- Việt hóa thuật ngữ: Thời gian ghi
- Gợi ý:

### `File size limit`

- Việt hóa thuật ngữ: Dung lượng file tối đa
- Gợi ý:

### `Binary conversion: MB = 1,048,576 bytes; GB = 1,073,741,824 bytes`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Disk reserve`

- Việt hóa thuật ngữ: Dung lượng ổ đĩa còn lại
- Gợi ý:

### `Output directory`

- Việt hóa thuật ngữ: Thư mục chứa file ghi
- Gợi ý:

### `Relative to the backend recording root`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Choose output directory`

- Việt hóa thuật ngữ: Chọn thư mục chứa file ghi
- Gợi ý:

### `Choose a folder below the recording root`

- Việt hóa thuật ngữ: 
- Gợi ý:

### `Choose recording directory`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Recording directories`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Default root`

- Việt hóa thuật ngữ:
- Gợi ý:

### `No directories found`

- Việt hóa thuật ngữ: Không có bản ghi nào được tìm thấy
- Gợi ý:

### `New recording directory`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Create recording directory`

- Việt hóa thuật ngữ: Tạo thư mục
- Gợi ý:

### `Create`

- Việt hóa thuật ngữ: Tạo
- Gợi ý:

### `Loading directories…`

- Việt hóa thuật ngữ: Đang tải
- Gợi ý:

### `Close directory picker`

- Việt hóa thuật ngữ:
- Gợi ý:

### `File prefix`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Disk capacity`

- Việt hóa thuật ngữ:
- Gợi ý:

### `{available} available / {total} total`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Unavailable`

- Việt hóa thuật ngữ:
- Gợi ý:

### `IDLE`

- Việt hóa thuật ngữ:
- Gợi ý:

### `STARTING`

- Việt hóa thuật ngữ:
- Gợi ý:

### `RECORDING`

- Việt hóa thuật ngữ:
- Gợi ý:

### `STOPPING`

- Việt hóa thuật ngữ:
- Gợi ý:

### `FINALIZING`

- Việt hóa thuật ngữ:
- Gợi ý:

### `COMPLETED`

- Việt hóa thuật ngữ:
- Gợi ý:

### `FAILED`

- Việt hóa thuật ngữ:
- Gợi ý:

### `{count} traces`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Queue {percent}%`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Batches {count} · Gaps {count} · Lost {count}`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Stopped by user`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Recording time reached`

- Việt hóa thuật ngữ:
- Gợi ý:

### `File size limit reached`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Low disk space`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Recorder queue overrun`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Analyzer disconnected`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Backend shutdown`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Recording write error`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Recording failed to start`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Recorder status: Queue {percent}%, {rejected} rejected, {gaps} gaps, {lost} lost`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Saving configuration…`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Record time must be a finite positive number of seconds.`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Enter a valid record time first.`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Enter a valid storage value first.`

- Việt hóa thuật ngữ:
- Gợi ý:

### `File size limit must be positive and at least 16 KiB.`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Disk reserve must be a finite non-negative value.`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Output directory must be relative to the recording root and cannot contain "..".`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Prefix must use 1–64 letters, digits, ".", "_" or "-", without "..".`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Unable to load recording configuration`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Recording status is temporarily unavailable`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Unable to save recording configuration`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Unable to start recording`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Unable to stop recording`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Unable to list recording directories`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Enter a safe relative directory below the recording root.`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Unable to create recording directory`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Recording failed`

- Việt hóa thuật ngữ:
- Gợi ý:

## 9. Section `Playback`

### `Playback`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Playback recording`

- Việt hóa thuật ngữ:
- Gợi ý:

### `No playable recordings`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Refresh recordings`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Open recording`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Open`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Previous trace`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Back 5 seconds`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Play playback`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Pause playback`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Forward 5 seconds`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Next trace`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Stop playback`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Playback timeline`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Auto Loop`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Toggle Auto Loop`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Run AI`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Toggle Run AI`

- Việt hóa thuật ngữ:
- Gợi ý:

### `On`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Off`

- Việt hóa thuật ngữ:
- Gợi ý:

### `{count} points`

- Việt hóa thuật ngữ:
- Gợi ý:

### `CONFIG {id} · Pauses {count} · Lost {count}`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Loops {count}`

- Việt hóa thuật ngữ:
- Gợi ý:

### `IDLE`

- Việt hóa thuật ngữ:
- Gợi ý:

### `OPENING`

- Việt hóa thuật ngữ:
- Gợi ý:

### `READY`

- Việt hóa thuật ngữ:
- Gợi ý:

### `PLAYING`

- Việt hóa thuật ngữ:
- Gợi ý:

### `PAUSED`

- Việt hóa thuật ngữ:
- Gợi ý:

### `SEEKING`

- Việt hóa thuật ngữ:
- Gợi ý:

### `STOPPING`

- Việt hóa thuật ngữ:
- Gợi ý:

### `COMPLETED`

- Việt hóa thuật ngữ:
- Gợi ý:

### `FAILED`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Unable to list recordings`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Playback status unavailable`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Playback request failed`

- Việt hóa thuật ngữ:
- Gợi ý:

## 10. Thuật ngữ dùng chung và nhãn hỗ trợ truy cập

### `OFF`

- Việt hóa thuật ngữ: TẮT
- Gợi ý:

### `ON`

- Việt hóa thuật ngữ: BẬT
- Gợi ý:

### `Increase {control label}`

- Việt hóa thuật ngữ: TĂNG
- Gợi ý:

### `Decrease {control label}`

- Việt hóa thuật ngữ: GIẢM
- Gợi ý:

### `{control label} unit`

- Việt hóa thuật ngữ:
- Gợi ý:

### `dBm`

- Việt hóa thuật ngữ:
- Gợi ý:

### `dB`

- Việt hóa thuật ngữ:
- Gợi ý:

### `dBFS`

- Việt hóa thuật ngữ:
- Gợi ý:

### `Hz / kHz / MHz / GHz`

- Việt hóa thuật ngữ:
- Gợi ý:

### `s / ms`

- Việt hóa thuật ngữ:
- Gợi ý:

### `B / KiB / MiB / GiB / TiB / MB / GB`

- Việt hóa thuật ngữ:
- Gợi ý:

### `FPS`

- Việt hóa thuật ngữ:
- Gợi ý:

## 11. Nội dung động cần có quy tắc Việt hóa riêng

### `Backend/SDK error text`

Ví dụ: lỗi thiết bị, lỗi ghi file, lỗi restore source hoặc lỗi API được backend
trả về nguyên văn và hiển thị trong `control-error`, `record-error` hoặc
`rf-path-warning`.

- Việt hóa thuật ngữ:
- Gợi ý:

### `RF path capability label`

Backend có thể cung cấp tên RF1–RF8 khác các fallback đã liệt kê. Không nên dịch
phần định danh `RF1`–`RF8`, nhưng cần quyết định quy tắc cho phần mô tả theo sau.

- Việt hóa thuật ngữ:
- Gợi ý:

### `Recording filename and user directory`

Tên tệp `.san90rta`, prefix và thư mục do người dùng đặt là dữ liệu, không phải
chuỗi giao diện.

- Việt hóa thuật ngữ:
- Gợi ý:
