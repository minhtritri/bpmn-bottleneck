# Slide đồ án BPMN — Công ty X

Bộ trình bày tiếng Việt gồm **30 slide, tỷ lệ 16:9**, với ghi chú thuyết trình cho
từng trang. Thành viên để `[Bổ sung sau]` trên slide 1 và 30.

## File chính

- `BPMN_CongTyX_30slides.pptx`: PowerPoint chỉnh sửa được. Bảng, biểu đồ thanh,
  heatmap và sơ đồ luồng được tạo bằng textbox/shape native; không phải ảnh chụp cả trang.
- `BPMN_CongTyX_30slides.pdf`: bản xem trước dùng chung tọa độ/font/nội dung với
  PPTX; được tạo trực tiếp từ layout, không phải bản render qua Microsoft Office.
- `speaker_notes.md`: ghi chú tập thuyết trình; nội dung này cũng nằm trong Notes của PPTX.
- `slide_sources.json`: nội dung/nguồn từng slide và hash của artifact được dùng.
- `preview/`: ảnh từng slide và ba contact sheet để kiểm tra bố cục.
- `validation.json`, `layout_audit.json`: kiểm tra số trang, nội dung tiếng Việt,
  vị trí shape và kích thước textbox.

## Mạch nội dung

1–4: bài toán, câu hỏi nghiên cứu và kiến thức áp dụng. 5–6: quy trình và vòng lặp
theo lớp. 7–10: dữ liệu, audit, pipeline và định nghĩa phép đo. 11–17: bằng chứng
điểm nghẽn, độ nhạy, QC, lượt lặp và Pareto. 18: Process Mining. 19–24: thiết kế,
đánh giá ML và chính sách cảnh báo. 25–28: To-Be và ba estimand cải tiến riêng.
29–30: tái lập, giới hạn, bước kiểm chứng tiếp theo và kết luận.

## Tạo lại bằng uv

Môi trường slide tách khỏi `src` để giữ nguyên lockfile và hash của thực nghiệm.
Script chỉ đọc kết quả pipeline đã có; không sửa Excel hoặc huấn luyện lại mô hình.

```sh
cd /Users/trids/master/BPMN/FInal_project/presentation
export UV_CACHE_DIR="$PWD/.uv-cache"
uv sync --locked
uv run --locked python build_slides.py
```

Yêu cầu Python 3.11/3.12 và font Arial trên macOS/Windows, hoặc DejaVu Sans trên
Linux. Không cần PowerPoint hay LibreOffice để tạo file.

Các bảng/biểu đồ chính đọc CSV/JSON. Phần luận giải và speaker notes mô tả bộ kết
quả đã kiểm chứng ngày 25/10/2026; nếu thay nhãn, cấu hình hoặc dữ liệu thực nghiệm,
cần rà soát lại phần luận giải sau khi tạo lại. Chỉ thay tên thành viên thì chỉnh
trực tiếp slide 1/30, hoặc thay placeholder trong script trước khi chạy.

Số ML trên slide 22 là **trung bình độ đo từng seed**. Slide 23 là **ensemble**,
được ghi riêng. Nhãn `calendar_v1` khác D5 cũ; không so trực tiếp điểm số với E1.
Kịch bản cải tiến là giả định, không được gọi là thành tích đã đạt tại doanh nghiệp.
