# Syntax Rows — Đặc tả gameplay

> Chế độ đặc trưng của Syntax Stack. Bám theo hồ sơ (trang 3, 4, 6, Hình 1): mỗi hàng của lưới là một dòng lệnh Python, thụt lề thể hiện bằng vị trí cột, hàng chỉ được dọn khi validator xác nhận. Bản này bổ sung luật chi tiết để xây MVP (3–5 màn Beginner).

## 1. Ý tưởng trong một câu

Mỗi khối là một phím mang một mảnh mã (`for`, `i`, `range(3)`, `:`). Người chơi đặt phím lên các hàng để viết chương trình, nhấn Chạy, và các hàng chỉ biến mất khi chương trình chạy đúng.

## 2. Bàn chơi

- Lưới **10 cột × 4–7 hàng** (mỗi màn tự quy định số hàng = số dòng của lời giải + 1–2 hàng trống).
- **Mỗi hàng = một dòng lệnh**, đọc từ trên xuống dưới. Hàng trống bị bỏ qua.
- **Hai cột đầu là ô thụt lề** (viền nét đứt). Khối đầu tiên của hàng nằm ở cột 0 → không thụt lề, cột 1 → thụt 1 mức, cột 2 → thụt 2 mức. Khối không được bắt đầu xa hơn cột 2.
- Mỗi mảnh mã có **độ rộng 1u, 2u hoặc 3u** (như phím trên bàn phím): `:` và `i` là 1u, `print(i)` hay `range(3)` là 3u.
- Các mảnh trong một hàng được ghép theo thứ tự cột, cách nhau bằng một dấu cách. Khoảng trống giữa các mảnh không có ý nghĩa.
- Có ô **xem trước** luôn hiện đoạn mã đang ghép được (có tô màu cú pháp và số dòng).

## 3. Khay mảnh mã

- Mỗi màn có một bộ mảnh cố định: đủ mảnh cho lời giải **cộng 2–4 mảnh gây nhiễu** (ví dụ `range(2)`, `range(4)` bên cạnh `range(3)`).
- Mỗi mảnh dùng **một lần**. Kéo mảnh từ khay lên lưới; kéo ngược về khay hoặc chạm vào mảnh trên lưới để trả về khay; kéo giữa các vị trí trên lưới để di chuyển.
- Màu mảnh: từ khóa và cú pháp (`for`, `in`, `:`, `=`) dùng màu trung tính; mảnh mang chủ đề dùng màu chủ đề (giống Code Rescue) để người học nhận ra nhóm kiến thức.

## 4. Chạy kiểm tra

Nhấn **Chạy kiểm tra** (phím Enter):

- **Đạt** (chạy được và đầu ra khớp test case, đúng các cấu trúc bắt buộc của màn): các hàng **được dọn lần lượt từ trên xuống**, ô đầu ra in kết quả, màn hoàn thành.
- **Chưa đạt**: không hàng nào biến mất. Validator báo:
  - **hàng bị lỗi** (số dòng, tô đỏ ở lề),
  - **nhóm lỗi**: sai cú pháp, thiếu dấu hai chấm, sai thụt lề, sai thứ tự, đầu ra không khớp, thiếu cấu trúc bắt buộc (ví dụ màn vòng lặp mà không dùng `for`),
  - đầu ra thực tế so với đầu ra mong đợi.
- Đúng như Hình 1 trong hồ sơ: **hàng đầy chưa chắc được dọn**; hàng chỉ biến mất khi mã đạt kiểm tra.
- **Thử lại không giới hạn.** Syntax Rows là chế độ học, không có thua ván (khác Code Rescue).

## 5. Gợi ý

3 cấp như hồ sơ (Khái niệm → Định hướng → Cụ thể), mở lần lượt, dựa trên **nhóm lỗi của lần chạy gần nhất**. Trước lần chạy đầu tiên chỉ có gợi ý chung của màn. Gợi ý soạn sẵn luôn có; AI gia sư thay thế khi được tích hợp (tuần 4).

## 6. Sao và điểm

| Sao | Điều kiện |
| --- | --- |
| ★★★ | Đạt ngay lần chạy đầu, không dùng gợi ý |
| ★★ | Đạt trong ≤ 3 lần chạy và dùng tối đa Gợi ý 1 |
| ★ | Đạt |

- Điểm màn = 300 × (sao / 3) + 50 × số mảnh gây nhiễu **không** bị dùng trong lần chạy đạt.
- XP và sao lưu theo người chơi; hoàn thành màn mở khóa màn tiếp theo; có thể chơi lại để lấy thêm sao.

## 7. Năm màn Beginner (MVP)

| # | Tên | Mục tiêu | Lời giải | Mảnh gây nhiễu |
| --- | --- | --- | --- | --- |
| 1 | Biến đầu tiên | In ra `7` | `diem = 7` / `print(diem)` | `8`, `print("diem")` |
| 2 | Đậu hay trượt | In ra `Đậu` | `diem = 8` / `if diem >= 5 :` / ⇥ `print("Đậu")` | `<`, `print("Trượt")`, `=` (thừa) |
| 3 | Đếm đến ba | In ra `0 1 2` (mỗi số một dòng) | `for i in range(3) :` / ⇥ `print(i)` | `range(2)`, `range(4)`, `while` |
| 4 | Cộng dồn | In ra `6` | `tong = 0` / `for i in range(1, 4) :` / ⇥ `tong = tong + i` / `print(tong)` | `range(1, 3)`, mảnh `print(tong)` thứ hai (để thử bẫy thụt lề) |
| 5 | Hàm nhân đôi | In ra `8` | `def gap_doi(x) :` / ⇥ `return x * 2` / `print(gap_doi(4))` | `return x + 2`, `print(x * 2)` |

Màn 3 chính là ví dụ nhiệm vụ trong hồ sơ: nếu đặt `range(2)`, validator báo đầu ra không khớp (`0 1`) và gợi ý nhắc giá trị kết thúc của `range()`.

Màn 4 có bẫy học tập: đặt `print(tong)` thụt lề vào trong vòng lặp sẽ in `1 3 6` thay vì `6`, và validator chỉ đúng hàng đó là hàng lỗi.

## 8. Liên hệ với Code Rescue

| | Code Rescue | Syntax Rows |
| --- | --- | --- |
| Khối | Khối hình, mang màu chủ đề | Mảnh mã thật, rộng 1u–3u |
| Dọn hàng | Giải câu đố khi hàng đầy | Chương trình chạy đúng |
| Thất bại | Sai 2 lần là thua ván | Thử lại không giới hạn |
| Mục đích | Luyện phản xạ, có áp lực | Học viết mã, ít áp lực |

Hai chế độ dùng chung bàn phím (lưới), validator, gợi ý 3 cấp và cách tính chủ đề bằng màu, nên người chơi chuyển qua lại không phải học lại giao diện. Pilot so sánh hai chế độ như kế hoạch trong hồ sơ.
