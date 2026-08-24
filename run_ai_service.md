# Đã lỗi thời: backend giờ tự spawn tools/yolo_detection.py, không cần chạy
# tay nữa. Xem docs/deployment.md. Lệnh export OpenVINO ở cuối file này vẫn
# còn dùng được khi cần export lại model.

cd /home/tuancoi/Desktop/uav_new/project/backend
python3 app.py


cd /home/tuancoi/Desktop/san90
python3 tools/yolo_detection.py \
  --connect tcp://127.0.0.1:5557 \
  --model ai_detect/weights/best_openvino_model \
  --publish tcp://127.0.0.1:5558 \
  --review-publish tcp://127.0.0.1:5555

# đổi sang openvinno
cd /home/tuancoi/Desktop/san90
python3 -c "from ultralytics import YOLO; YOLO('ai_detect/weights/best.pt').export(format='openvino')"
