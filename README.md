# BPMN Bottleneck — Công ty X

Mã nguồn đồ án phân tích điểm nghẽn trong quy trình sản xuất bằng BPMN và Process
Mining, thực nghiệm dự báo WIP và đánh giá các hướng cải tiến nhóm đề xuất.

Repository chỉ chứa **code, cấu hình, lockfile, test và tài liệu kỹ thuật**.
Dữ liệu doanh nghiệp, BPMN đầu vào, tài liệu học phần, kết quả thực nghiệm,
model đã huấn luyện, slide và PDF sinh ra được giữ cục bộ và loại khỏi Git.

## Cấu trúc

```text
src/
  bpmn_project/       # Chuẩn hóa, audit, phân tích, mining, ML, kịch bản
  tests/              # Kiểm tra logic và hồi quy số học
  scripts/            # Chạy notebook và kiểm chứng kết quả
  config.toml         # Cấu hình thực nghiệm
  demo.ipynb          # Notebook nguồn, không chứa output thực nghiệm
  pyproject.toml
  uv.lock
presentation/
  build_slides.py     # Tạo PPTX và PDF từ kết quả đã kiểm chứng ở máy cục bộ
  pyproject.toml
  uv.lock
```

## Chạy bằng uv

Yêu cầu Python 3.11/3.12, `uv` và Git. Xem lưu ý build dependency Gensim trong
[hướng dẫn pipeline](src/README.md).

```sh
cd src
export UV_CACHE_DIR="$PWD/.uv-cache"
uv sync --locked
uv run --locked pytest -q
```

Các test dùng workbook thật sẽ skip nếu máy chưa có dữ liệu riêng. Để chạy toàn
bộ pipeline, cung cấp riêng các đầu vào sau ở thư mục gốc repository:

- `CongTyX_Event log.xlsx`: workbook dữ liệu đúng schema.
- `BPMN/`: các mô hình BPMN đầu vào; pipeline sử dụng `Tong the BPMN.bpmn`.

Không đổi tên file hoặc các sheet của workbook nếu chưa cập nhật code đọc dữ liệu.
Các tài liệu kế hoạch/học phần không phải đầu vào bắt buộc để chạy phân tích.

```sh
uv run --locked congtyx all
uv run --locked python scripts/execute_demo.py
uv run --locked python scripts/verify_outputs.py
```

Kết quả được ghi trong `src/outputs/` và không được đưa lên Git. Có thể dùng
`--data-dir`, `--output`, `--config` để chỉ định vị trí khác; xem
[README kỹ thuật](src/README.md) để biết schema, định nghĩa nhãn và giới hạn.

## Tạo slide

Sau khi có một bản chạy đầy đủ đã được kiểm chứng:

```sh
cd presentation
export UV_CACHE_DIR="$PWD/.uv-cache"
uv sync --locked
uv run --locked python build_slides.py
```

Xem [hướng dẫn slide](presentation/README.md). Script tạo PowerPoint/PDF ở máy
cục bộ; phần luận giải cần được rà lại nếu thay bộ dữ liệu hoặc cấu hình.

Các kết quả kịch bản thể hiện đánh giá theo giả định cho hướng xử lý nhóm đề xuất,
chưa phải mức cải thiện đã đo tại doanh nghiệp.
