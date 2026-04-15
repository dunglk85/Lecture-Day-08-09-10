# Quality report — Lab Day 10 (nhóm)

**run_id (before):** `sprint3-before`  
**run_id (after):** `sprint3-after`  
**Ngày:** 2026-04-15

---

## 1. Tóm tắt số liệu

| Chỉ số | Trước (sprint3-before) | Sau (sprint3-after) | Ghi chú |
|--------|------------------------|---------------------|---------|
| raw_records | 7 | 7 | Cùng input `sprint3_corrupt.csv` |
| cleaned_records | 6 | 6 | Before: chunk "14 ngày" lọt qua do `--no-refund-fix` |
| quarantine_records | 1 | 1 | HR stale (2025) bị quarantine ở cả 2 scenario |
| Expectation halt? | **YES** — `refund_no_stale_14d_window` FAIL (violations=1) | **NO** — all 8 expectations OK | `--skip-validate` cho before chạy tiếp embed dù halt |

---

## 2. Before / after retrieval (bắt buộc)

> Dẫn link: [`eval_sprint3_before.csv`](../artifacts/eval/eval_sprint3_before.csv) và [`eval_sprint3_after.csv`](../artifacts/eval/eval_sprint3_after.csv)

### Câu hỏi then chốt: `q_refund_window`

**Trước (corrupt — `--no-refund-fix --skip-validate`):**

```
q_refund_window | top1_doc_id=policy_refund_v4
top1_preview: "Yêu cầu hoàn tiền được chấp nhận trong vòng 14 ngày làm việc kể từ xác nhận đơn."
contains_expected=yes | hits_forbidden=yes ← stale "14 ngày" có mặt trong top-k
```

→ **Retrieval trả về chunk chứa thông tin SAI** (14 ngày thay vì 7 ngày). Nếu LLM đọc chunk này, câu trả lời sẽ sai hoàn toàn.

**Sau (clean — fix applied):**

```
q_refund_window | top1_doc_id=policy_refund_v4
top1_preview: "Yêu cầu hoàn tiền được chấp nhận trong vòng 7 ngày làm việc kể từ xác nhận đơn."
contains_expected=yes | hits_forbidden=no ← không còn "14 ngày" trong top-k
```

→ **Retrieval trả về chunk chính xác** (7 ngày). Pipeline fix stale refund window đã loại bỏ thông tin lỗi thời.

---

### Merit: `q_leave_version` (HR versioning)

**Trước (corrupt):**

```
q_leave_version | top1_doc_id=hr_leave_policy
top1_preview: "Nhân viên dưới 3 năm kinh nghiệm được 12 ngày phép năm theo chính sách 2026."
contains_expected=yes | hits_forbidden=no | top1_doc_expected=yes
```

**Sau (clean):**

```
q_leave_version | top1_doc_id=hr_leave_policy
top1_preview: "Nhân viên dưới 3 năm kinh nghiệm được 12 ngày phép năm theo chính sách 2026."
contains_expected=yes | hits_forbidden=no | top1_doc_expected=yes
```

→ Cả trước và sau đều OK vì baseline rule đã quarantine bản HR cũ (10 ngày, `effective_date < 2026-01-01`). **Đây chính là bằng chứng cleaning rule hoạt động đúng**: stale HR version bị loại trước khi embed, nên retrieval luôn trả đúng bản 2026 (12 ngày).

Nếu **tắt rule quarantine HR stale** (giả lập: cho `effective_date >= 2025-01-01` qua), top-k sẽ chứa cả "10 ngày phép năm" (`hits_forbidden=yes`) — LLM có thể trả lời sai version.

---

## 3. Freshness & monitor

```
freshness_check=FAIL {"latest_exported_at": "2026-04-10T08:00:00", "age_hours": 120.2, "sla_hours": 24.0, "reason": "freshness_sla_exceeded"}
```

- **SLA chọn:** 24 giờ (production-grade — dữ liệu policy cần cập nhật hàng ngày)
- **Trạng thái hiện tại:** FAIL — export cuối cùng cách đây ~120 giờ (5 ngày), vượt SLA
- **Hành động:** Source owner cần re-export CSV từ CMS. Alert nên gửi qua Slack/email khi SLA bị vi phạm
- **E8 (exported_at_within_30d):** Expectation warn-level bổ sung kiểm tra từng chunk — phát hiện chunk cũ >30 ngày trước khi freshness SLA manifest-level phát hiện

---

## 4. Corruption inject (Sprint 3)

### Kịch bản inject

Sử dụng file `data/raw/sprint3_corrupt.csv` với 7 rows, trong đó:
- **Row 2:** Chunk policy refund chứa cửa sổ sai "14 ngày làm việc" (thay vì 7 ngày theo v4)
- **Row 6:** Chunk HR leave policy bản cũ 2025 ("10 ngày phép năm", `effective_date=2025-01-01`)

**Lệnh inject (before):**
```bash
python etl_pipeline.py run \
  --raw data/raw/sprint3_corrupt.csv \
  --no-refund-fix --skip-validate \
  --run-id sprint3-before
```

**Kết quả:**
- Expectation `refund_no_stale_14d_window` **FAIL (halt)** nhưng `--skip-validate` bypass halt → embed dữ liệu bẩn
- Row 6 bị quarantine bởi baseline rule `stale_hr_policy_effective_date` (hoạt động đúng)
- Eval `q_refund_window`: `hits_forbidden=yes` — retrieval trả về chunk stale

**Lệnh fix (after):**
```bash
python etl_pipeline.py run \
  --raw data/raw/sprint3_corrupt.csv \
  --run-id sprint3-after
```

**Kết quả:**
- All 8 expectations OK
- Rule fix stale refund: "14 ngày" → "7 ngày" + tag `[cleaned: stale_refund_window]` (R7 strip tag)
- Eval `q_refund_window`: `hits_forbidden=no` — retrieval sạch ✅

### Bảng so sánh retrieval

| question_id | Metric | Before (corrupt) | After (clean) |
|---|---|---|---|
| `q_refund_window` | `contains_expected` | yes | yes |
| `q_refund_window` | `hits_forbidden` | **yes** ❌ | **no** ✅ |
| `q_refund_window` | top-1 preview | "...14 ngày làm việc..." | "...7 ngày làm việc..." |
| `q_leave_version` | `contains_expected` | yes | yes |
| `q_leave_version` | `hits_forbidden` | no | no |
| `q_leave_version` | `top1_doc_expected` | yes | yes |
| `q_p1_sla` | `contains_expected` | yes | yes |
| `q_lockout` | `contains_expected` | yes | yes |

---

## 5. Hạn chế & việc chưa làm

- **Freshness SLA luôn FAIL** với dữ liệu mẫu vì `exported_at` cố định = `2026-04-10`. Cần kết nối CMS/API thực để có export tự động
- **Chưa test chunk overlap / semantic duplicate**: hai chunk có nội dung gần giống nhau nhưng khác text literal sẽ qua dedup, có thể gây retrieval noise
- **E7 là defense-in-depth cho R8**: nếu R8 bị bypass (bug/config), E7 sẽ halt pipeline. Chưa có test case chứng minh E7 fail độc lập (cần mock disable R8)
- **Eval chỉ dùng keyword matching**: chưa có LLM-as-Judge cho faithfulness/relevance score. Có thể tích hợp eval từ Day 09
