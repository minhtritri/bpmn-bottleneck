# Công ty X — code đồ án BPMN

Phạm vi đã tinh chỉnh: **phân tích điểm nghẽn trong quy trình sản xuất bằng BPMN và
Process Mining; đánh giá kịch bản cải tiến**. Dự báo ùn WIP bằng Graph ML là phần
thực nghiệm bổ sung, được so sánh với quy tắc đơn giản và Random Forest.

Đây là hướng dẫn kỹ thuật và hợp đồng dữ liệu, chưa phải report hay slide đồ án.
Các file Excel/BPMN/DOCX/PDF gốc ở thư mục cha được giữ nguyên.

## Chạy bằng uv

Yêu cầu Python 3.11 hoặc 3.12 và `uv`. Không dùng pip/venv thủ công.

```sh
cd /Users/trids/master/BPMN/FInal_project/src
export UV_CACHE_DIR="$PWD/.uv-cache"
export MPLCONFIGDIR="$PWD/.mpl-cache"
export XDG_CACHE_HOME="$PWD/.cache"
uv sync --locked
uv run --locked pytest -q
uv run --locked congtyx all
```

Hoặc `make sync`, `make test`, `make check`, `make run`.

Sau bản chạy đầy đủ, mở `demo.ipynb` với kernel Python trong `.venv`, hoặc chạy
`make demo` / `uv run --locked python scripts/execute_demo.py` để xuất
`outputs/demo_executed.ipynb` có sẵn bảng và hình. Script chỉ tạo kernelspec cục bộ
trong `.jupyter/`, không đăng ký kernel toàn máy. Notebook đọc kết quả, không tự chạy
lại training và không phải report đồ án.

`uv.lock` khóa phiên bản dependency đã dùng. `config.toml` lưu toàn bộ giả định,
seed, kích thước embedding, ngưỡng nhãn và tham số mô phỏng.

Gensim được khóa vào commit `ecf22c266f3b8930610114c149d8991ed14e2a16` của bản sửa
[BLAS dot product = −1](https://github.com/piskvorky/gensim/pull/3668), thay vì wheel
4.4.0 có cảnh báo/sai số đã quan sát khi chạy embedding. Đây là bản sửa upstream
chưa merge tại thời điểm triển khai; chỉ thay khai báo BLAS và thêm regression test.
`uv sync --locked` có thể cần Git và C compiler để build dependency này. Test riêng
kiểm tra điểm số Word2Vec đối xứng khi dot product ±1; không tắt cảnh báo để che lỗi.

Lần đầu cần mạng để tải dependency. Không cần Graphviz để chạy pipeline: PNML,
DOT và BPMN vẫn được xuất; nếu máy có lệnh `dot` thì có thêm SVG Petri net và layout
BPMN discovery. Các biểu đồ Matplotlib luôn xuất PNG + SVG.

```sh
uv run --locked congtyx audit
uv run --locked congtyx analyze
uv run --locked congtyx mine
uv run --locked congtyx forecast
uv run --locked congtyx simulate
uv run --locked congtyx all --quick
```

- Mỗi stage đọc lại input, chuẩn hóa và audit; `simulate` tự chạy phân tích cần thiết.
- `all` chạy toàn bộ theo thứ tự. `--quick` dùng 1 seed, ít walk/cây hơn, mặc định ghi
  vào `outputs_quick/`; chỉ dùng kiểm tra pipeline, không dùng số này cho báo cáo.
- Bản đầy đủ dùng 5 seed, 300 cây/RF, Node2Vec 16 chiều và 10.000 lượt mô phỏng.
- Có thể truyền `--data-dir`, `--output`, `--config`. Không dùng chung output cho hai
  cấu hình khác nhau nếu muốn lưu cả hai thực nghiệm. Các file kết quả cùng tên được ghi lại.
- `metadata/run_all.json` phải có `status: success` và `quick: false` trước khi dùng
  bộ `outputs/` làm kết quả chính thức. Stage lẻ chỉ xác nhận chính stage đó.
- `make verify` tính lại mọi nhóm độ đo từ dự đoán lưu, nạp 12 model seed 42 để
  tái tạo xác suất, kiểm tra hash input/code và các bất biến mô phỏng. Kết quả ở
  `metadata/verification.json`; nên chạy sau `make demo` để inventory gồm notebook.

## Pipeline và file code

| Module | Trách nhiệm |
|---|---|
| `data.py` | Đọc workbook, hash input, chuẩn hóa độc lập A6, audit và provenance |
| `analysis.py` | Thời gian quan sát, QC, lỗi, lượt lặp theo lớp, DFG, chuyển người thực hiện |
| `mining.py` | Inductive/Alpha discovery, replay và kiểm tra cấu trúc BPMN |
| `features.py` | Lịch tháng đầy đủ, feature quá khứ, nhãn phiên bản `calendar_v1` |
| `graph_ml.py` | Routing graph, trọng số WIP quá khứ, Node2Vec thực, Procrustes tuần tự |
| `models.py` | Baseline, RF, graph ablation, validation, holdout, walk-forward, độ đo |
| `simulation.py` | Replay khoảng cách, Monte Carlo workload làm lại, timer QC7, BPMN phạm vi hẹp |
| `visuals.py` | Routing/DFG và PCA embedding; xuất tọa độ để kiểm tra |
| `cli.py` | Điều phối, ghi trạng thái thực thi và danh mục artifact |

## Dữ liệu và độ tin cậy

| Nguồn | Dùng làm gì | Giới hạn |
|---|---|---|
| A1 MES | 1.397 sự kiện của 8 serial; nguồn thời gian chính | Chọn có chủ đích, nhiều làm lại, một số trace thiếu kết thúc |
| A2/A1 định mức | So sánh và proxy thời lượng operation | Khác phiên bản BOM, không phải đo trực tiếp thời gian gia công |
| A5 | Ánh xạ MES → task; tái triển khai quy tắc trong Python | Bảng AI hỗ trợ tạo, cần xác nhận nghiệp vụ |
| A6–A11 | Đối chiếu kết quả cũ | Không dùng cache công thức làm kết quả chính |
| B1/B3/C1 | Bằng chứng tổng hợp làm lại/hủy/WIP | Khác kỳ, khác mẫu số; không ghép tùy ý thành xác suất gateway |
| D1/D2/D4 | Nguồn snapshot cho thực nghiệm trạm–tháng | Không có báo cáo raw và code tạo các bảng này |
| D3 | Chỉ xuất để đối chiếu | Không đưa trọng số không rõ công thức vào mô hình |
| D5/E1–E4 | Đối chiếu nhãn và kết quả cũ | Không dùng nhãn/dự báo tương lai làm feature |

`metadata/manifest.json` lưu hash SHA-256 của input, phiên bản thư viện, cấu hình và
giới hạn nguồn dữ liệu. Không có bước gọi API AI hoặc gửi dữ liệu doanh nghiệp ra mạng.

## Hợp đồng event log

`data/events.csv` giữ nguyên thứ tự nguồn và chứa:

| Trường | Ý nghĩa |
|---|---|
| `event_id`, `source_row` | ID ổn định và dòng Excel A1 để truy ngược |
| `case_id`, `product_id`, `product_level` | Serial, sản phẩm, cấp thành phẩm/bán thành phẩm |
| `station_id`, `activity_mes`, `resource` | Trạm và nhãn/tài khoản gốc đã ẩn danh |
| `bpmn_activity`, `bpmn_node_candidates` | Nhãn chuẩn, toàn bộ ID task có thể phù hợp; không bịa ID duy nhất |
| `paint_layer`, `activity_layer` | Lớp sơn riêng; lớp mới là công việc theo tuyến |
| `outcome`, `outcome_detail` | Kết quả và lỗi gốc |
| `start_time`, `end_time` | Mốc nguồn; timer đã gộp có end là UNBLOCK |
| `source_start_time`, `source_end_time` | Timestamp gốc trước khi gộp timer, giữ để đối chiếu |
| `raw_duration_min`, `recorded_duration_min` | Complete−Start gốc; giá trị âm bị đánh dấu và để thiếu ở bản phân tích |
| `raw_gap_min`, `gap_min` | Start−Complete dòng trước cùng case, theo thứ tự nguồn; không phải ready-time queue |
| `intercompletion_min` | Complete−Complete trước, chỉ giữ giá trị không âm |
| `standard_min` | Định mức được cung cấp trong A1; chưa tái lập ghép BOM từ raw |
| `include_control`, `handling`, `paired_source_row` | Quy tắc lọc riêng cho kiểm tra luồng, không xóa log gốc |

Quy tắc quan trọng:

1. Hai dòng âm thời gian được giữ và gắn cờ; không tự sửa AM/PM.
2. QC7 BLOCK/UNBLOCK cùng case/trạm gộp thành timer. Trạng thái khóa ở trạm khác
   không trở thành task nghiệp vụ.
3. SCRAP ngay trước RECOVER cùng case/trạm: bỏ cả hai khỏi log kiểm tra luồng,
   vẫn giữ trong bảng sự kiện. Các quyết định hủy khác không tự động bỏ.
4. Vận chuyển giữ cho phân tích thời gian, loại khỏi mô hình luồng theo phạm vi A5.
5. Task chưa có trong BPMN mang nhãn `LOG_ONLY: ...`; không bỏ để tăng fitness.
6. Đếm lượt lặp theo `(case, task, lớp)`, tách lớp sơn tiếp theo khỏi rework.
7. `observed_span` là khoảng quan sát, không tự coi là Cycle Time hoàn thành.
8. Timestamps là đồng hồ nguồn không timezone; dùng giờ lịch. Không tự gán múi giờ
   hoặc coi đây là giờ làm việc. Chủ dữ liệu đã điều chỉnh mốc lịch.

## Process Mining và conformance

- DFG là các cặp liên tiếp trong **log đã lọc theo phạm vi**; tần suất không phải
  xác suất bắt buộc của tuyến. Log XES giữ thứ tự nguồn, có ID/dòng nguồn từng event.
- Chạy Inductive Miner (noise threshold 0,2) và Alpha Miner; xuất PNML/DOT, fitness
  và precision token-based. Discovery và replay dùng cùng 8 trace: chỉ mô tả mẫu.
- BPMN đầu vào là `Tong the BPMN.bpmn`, tránh ghép trực tiếp nhiều process chứa
  `callActivity` mà chưa xử lý việc gọi quy trình.
- File tổng thể này dừng ở sản phẩm đạt yêu cầu, chưa chứa task Đóng gói/Nhập kho
  như Hình 1. Ba event Đóng gói vì vậy vẫn hiện là thiếu ánh xạ trong phạm vi mô hình
  đang kiểm tra; không diễn giải chúng là sai nghiệp vụ và không xóa để tăng fitness.
- Kiểm tra cấu trúc đi qua gateway/sự kiện im lặng nhưng **không bỏ qua task bắt buộc**.
  Duy trì tập ứng viên khi nhiều node trùng tên. Sau sai lệch, kiểm tra tiếp ở mức cục bộ.
  `structurally_possible` không đồng nghĩa cả trace hợp lệ.
- Chạy thêm token replay với BPMN gốc. Thiếu đầu/cuối trace, task chưa ánh xạ và
  tên trùng đều có thể ảnh hưởng; không diễn giải toàn bộ fitness thấp là vi phạm nghiệp vụ.
- Chưa đánh giá guard dựa trên dữ liệu, số lượng, chi tiết lớp sơn hoặc ngữ nghĩa hủy
  toàn cục bằng replay. Timer 72h được kiểm tra riêng từ timestamp.
- Mạng chuyển người thực hiện chỉ là quan hệ quan sát; không đo utilization hoặc
  chứng minh nhân viên là bottleneck.

## Thực nghiệm dự báo

Đơn vị mẫu là **trạm–tháng**, dự báo tại cuối tháng `t` cho tháng `t+1`.
Không dùng mẫu event để huấn luyện dự báo tuần như plan cũ.

### Feature và nhãn

- Tạo đủ mọi tháng trong khoảng 01/2019–04/2021; 08/2019 và 02/2020 giữ missing.
- `lag1` là một tháng lịch trước, không phải một dòng quan sát trước.
- Median quá khứ dùng cửa sổ 6 tháng lịch trước `t`, ít nhất 3 quan sát; không gồm `t`.
- Baseline chỉ dùng WIP, tỷ trọng WIP, lag, median, thay đổi và chỉ báo lịch sử.
- Không dùng rework/scrap tháng hiện tại khi chưa biết ngày có báo cáo; không dùng
  sản lượng tương lai, `wip_next`, nhãn, dự báo E4 hay kết quả mô hình cũ.
- Imputer fit trên train, có missing indicators. Missing không bị đổi thành WIP=0.

Hai nhãn **được định nghĩa lại rõ ràng**, phiên bản `calendar_v1`:

1. `y_top20_next`: nằm trong `ceil(20% × số trạm)` WIP cao nhất tháng kế tiếp.
   Đồng hạng xử lý theo tên trạm để có ngân sách top-k cố định.
2. `y_surge_next`: `WIP(t+1) > max(20, 1.5 × median WIP quá khứ của t)`.

Nhãn thứ hai là tăng cao so với lịch sử, không bắt buộc tăng so với ngay tháng `t`.
Do thiếu quy tắc sinh D5 gốc và có sửa lịch tháng, không đối chiếu trực tiếp điểm số
mới với E1 như thể cùng thí nghiệm. File comparison ghi rõ từng khác biệt.

### Graph và Node2Vec

- Dùng cạnh D2 có `n_bom>0`, giới hạn trong 54 trạm có WIP. Không dùng cạnh chỉ
  xuất hiện ở MES hoặc số đếm MES tương lai để làm trọng số.
- Routing là snapshot chưa có lịch sử phiên bản: kết quả graph **có điều kiện** là
  topology này đã được biết tại thời điểm dự báo. Baseline WIP không phụ thuộc giả định đó.
- Tự tính trọng số ngữ cảnh WIP từ trung bình các snapshot có trong 3 tháng lịch
  đến `t`: `1 + 0.5 × (log1p(WIP nguồn) + log1p(WIP đích))`.
  Đây không phải số lượt chuyển thực tế.
- Tính degree có hướng và PageRank. Node2Vec dùng bản vô hướng, cộng trọng số
  cạnh đối ứng; second-order walk có p/q thật và Skip-gram negative sampling.
- 16 chiều, p=1, q=0,5, 30 walk/node, dài 20, window=5, 10 epoch, 1 worker.
- Căn giữa, chuẩn hóa từng vector, Procrustes với embedding kỳ trước theo chiều
  thời gian. Không căn chỉnh vào kỳ test tương lai; không chọn seed theo điểm test.
- Không diễn giải embedding là hiểu ngữ nghĩa XOR/AND hoặc là bằng chứng nhân quả.

### Đánh giá

- Train feature months 04/2019–06/2020 (11 kỳ hợp lệ sau khi loại cặp thiếu tháng).
- Test feature months 07/2020–03/2021; dự báo **08/2020–04/2021**: 486 dòng, 9 kỳ.
- Nhãn train cuối cùng có thể được biết cuối 07/2020, đúng cutoff dự báo đầu tiên;
  code kiểm tra không có nhãn train vượt cutoff.
- Validation trong train từ 01/2020; toàn bộ hyperparameter/ngưỡng cố định trước test.
- Đánh giá thêm baseline walk-forward: refit khi nhãn mới đã quan sát được, xuất
  riêng khỏi thí nghiệm holdout cố định.
- So sánh majority, persistence, RF chỉ mã trạm, RF WIP, RF + graph metrics,
  RF + Node2Vec, RF + cả hai và RF chỉ Node2Vec.
- Xuất precision/recall/F1 positive, balanced accuracy, ROC-AUC, average precision,
  confusion matrix, positive support, kết quả từng tháng và recall theo ngân sách top20%.
- Báo trung bình/độ lệch chuẩn 5 seed, tách riêng kết quả ensemble xác suất.
- Bootstrap theo **cả tháng**, không resample độc lập từng trạm. Khoảng 95% chỉ
  mang tính thăm dò vì ít tháng, có phụ thuộc thời gian và chưa phản ánh bất định dữ liệu nguồn.
- Đây là dự báo tháng tương lai tại trạm đã biết; chưa chứng minh khái quát cho trạm
  mới, sản phẩm mới hoặc nhà máy mới. Graph ML không phải thắng baseline mới có giá trị.

## Đánh giá cải tiến

Không có lịch ca, công suất, arrivals hoặc ready_time để hiệu chỉnh mô phỏng hàng
đợi tài nguyên. Vì vậy pipeline xuất **ba estimand riêng**, không cộng thành hiệu quả toàn nhà máy:

| Phân tích | Đầu vào | Kịch bản | Đầu ra |
|---|---|---|---|
| Replay khoảng cách vào chà nhám | Gap dương theo case MES | Giảm giả định 0/10/25/40%; có/không checklist 2 phút mỗi lượt sơn | Giờ thay đổi trên khoảng quan sát của từng case |
| Monte Carlo workload làm lại | R từ B1, median định mức task A1 | Giảm R 0/10/25/40%, cùng số ngẫu nhiên As-Is/To-Be | Phút làm lại cho 100 SP; đối chiếu kỳ vọng giải tích |
| QC7 timer/dispatch replay | Hai cặp BLOCK/UNBLOCK quan sát | Đủ ít nhất 72h và dispatch giả định ≤2h | Thời gian từ BLOCK đến QC7 dưới giả định |

- Monte Carlo dùng geometric-equivalent `r=R/(1+R)`; chưa chứng minh thực tế có
  các lần lặp độc lập. Định mức mỗi operation lấy từ mẫu khác với tổng thể B1, là proxy.
- Phần workload chỉ đo **làm lại**, không tính số lớp sơn theo tuyến là lỗi và không
  tuyên bố đó là Cycle Time hoặc mức tăng throughput.
- Checklist có chi phí; mức giảm lỗi do checklist là giả định cần thử nghiệm thực tế.
- Tỷ lệ B3 có mẫu số tổng đầu vào nhà máy, không phải xác suất hủy có điều kiện ở
  mỗi công đoạn. Không gán thẳng vào XOR để mô phỏng sai.
- C1 là snapshot cuối tháng. Không coi WIP/384 là thời gian một lượt đi qua trạm
  cho mọi sản phẩm hoặc suy ra công suất trạm từ nó.
- Hai BPMN As-Is/To-Be tạo mới chỉ là projection phạm vi chà nhám–sơn theo lớp;
  giữ nhánh QC/sửa/hủy và lớp tiếp theo. Chưa thay thế BPMN toàn nhà máy.

## Tìm kết quả để dùng về sau

| Thư mục/file trong `outputs/` | Công dụng |
|---|---|
| `audit/issues.csv`, `summary.json` | Lỗi dữ liệu và giới hạn phạm vi |
| `audit/excel_control_differences.csv` | Khác biệt code với lọc A6 |
| `data/events.csv` | Bảng sự kiện chuẩn hóa, truy nguyên đến A1 |
| `process/case_metrics.csv`, `task_timing.csv` | Số liệu thời gian chính |
| `process/timing_sensitivity.csv` | Độ nhạy khi bỏ từng case rất dài |
| `process/bottleneck_evidence.csv`, `bottleneck_contract.json` | Đối chiếu stock tổng thể, làm lại và thời gian mẫu; quy tắc sàng lọc minh bạch |
| `process/qc_outcomes.csv`, `qc_by_layer.csv` | Mẫu số kiểm tra và lỗi theo lớp |
| `process/paint_repeated_visits.csv` | Lặp trong cùng lớp; có ID event chứng minh |
| `process/defect_pareto.csv`, `defect_evidence.csv` | Pareto lỗi và dòng nguồn |
| `process/timer_evidence.csv` | Cặp chờ 72h và chờ sau mở khóa |
| `mining/structural_deviations.csv` | Sai lệch cục bộ để xác minh nghiệp vụ |
| `mining/discovery_quality.csv` | So sánh miner trên cùng mẫu |
| `mining/supplied_model_token_replay.csv` | Chẩn đoán replay với BPMN gốc |
| `forecast/feature_contract.json`, `graph_contract.json` | Định nghĩa thực nghiệm |
| `forecast/model_comparison.csv` | Trung bình và độ lệch chuẩn theo seed |
| `forecast/ensemble_metrics_month_bootstrap.csv` | Ensemble và khoảng bootstrap tháng |
| `forecast/test_predictions.csv`, `prediction_examples.csv` | Dự đoán từng trạm và ví dụ TP/FP/FN/TN |
| `forecast/alert_review_policy.csv` | Minh họa cảnh báo bằng RF WIP, tối đa top20% trạm/tháng; không chứa actual tương lai |
| `forecast/excel_*comparison.csv`, `excel_feature_differences.csv` | Khác biệt với Excel cũ |
| `scenarios/*sensitivity.csv`, `*replay*.csv` | Kết quả các giả định cải tiến |
| `figures/*.png`, `*.svg` | Hình raster và vector để tái sử dụng |
| `models/*.joblib` | Pipeline RF seed 42; chỉ nạp file do chính pipeline tạo |
| `metadata/artifact_inventory.csv` | Danh mục file, số dòng/cột, hash |

## Kiểm thử và tiêu chí hoàn thành code

Các test tập trung vào lỗi có thể làm sai kết luận: thay đổi tương lai không làm đổi
feature/graph quá khứ; tháng thiếu không bị nén; nhãn đúng t+1; p/q thực sự tác động
walk; Procrustes khôi phục phép quay; không bỏ qua task bắt buộc; nhãn train không
vượt cutoff; mô phỏng đồng nhất khi không can thiệp và đối chiếu kỳ vọng.

Trước khi lấy số làm report: kiểm tra `run_all.json`, audit, định nghĩa mẫu số, số
tháng test và sensitivity. Số liệu Excel cũ chỉ làm đối chiếu. Chưa được gọi kịch bản
mô phỏng là mức cải thiện đã đạt được tại Công ty X.

## Tài liệu kỹ thuật tham chiếu

- [PM4Py chính thức](https://github.com/process-intelligence-solutions/pm4py)
- [PM4Py API](https://github.com/process-intelligence-solutions/pm4py/blob/release/docs/source/api.rst)
- [Node2Vec — Grover & Leskovec, 2016](https://arxiv.org/abs/1607.00653)

API được kiểm tra thêm trên đúng phiên bản cài trong `uv.lock`; dùng tài liệu chính
thức để xác minh thuật toán, không đưa ví dụ bên ngoài vào dữ liệu Công ty X.
