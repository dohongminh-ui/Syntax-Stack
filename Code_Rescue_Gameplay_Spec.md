# Code Rescue — Đặc tả gameplay (bản mở rộng)

> Bản này thay thế mô tả Code Rescue hiện có trong hồ sơ (trang 2, 3, 4, 6). Syntax Rows giữ nguyên.
> Thay đổi chính: **hàng đầy không tự biến mất — người chơi phải giải một câu đố mã để "commit" hàng đó.** Mỗi câu đố chỉ có **1 lần trả lời**. Cả ván chỉ được **sai 1 lần**: lần sai đầu tiên để lại một **bug line** làm cảnh báo, lần sai thứ hai là **thua ván**.

---

## 1. Ý tưởng trong một câu

Xếp khối như block puzzle quen thuộc, nhưng mỗi hàng đầy là một "bản build" đang chờ: giải đúng câu đố mã để build thành công và dọn hàng. Bạn chỉ được build lỗi một lần, lần thứ hai thì hệ thống sập.

## 2. Vòng chơi

```
Đặt khối ──► Hàng/cột đầy? ──không──► Lượt tiếp theo
                 │ có
                 ▼
        Hàng bị KHÓA (phát sáng, lưới tạm dừng)
                 │
                 ▼
        Câu đố Rescue — 1 lần trả lời
        (chủ đề lấy theo màu khối trong hàng)
           │                         │
         Đúng                       Sai
           │                         │
           ▼                         ▼
   Dọn hàng + tính điểm      Đây là lần sai thứ mấy?
   + streak, có thể nhận        │               │
     vật phẩm                 Lần 1           Lần 2
                                │               │
                                ▼               ▼
                      Hàng → BUG LINE 🐞    SYSTEM CRASH
                      Trạng thái: 🟡 Cảnh báo  → thua ván
                      (sửa được bằng câu đố Debug
                       để trở lại 🟢 Ổn định)

Ngoài ra: không còn chỗ đặt khối → GAME OVER (có 1 lần "Last Commit")
```

Lưới 8×8, mỗi lượt có 3 khối để chọn, như thể loại block puzzle thông thường. Điểm khác biệt nằm ở bước "khóa hàng".

**Trạng thái build** luôn hiện ở góc màn hình:

| Trạng thái | Ý nghĩa |
| --- | --- |
| 🟢 Ổn định | Chưa sai lần nào, hoặc đã sửa xong bug line |
| 🟡 Cảnh báo | Đã sai 1 lần, trên lưới có 1 bug line. Sai thêm 1 lần nữa là thua |
| 🔴 Crash | Sai lần 2, ván kết thúc |

## 3. Màu khối = chủ đề Python (cơ chế chiến thuật chính)

Mỗi khối mang màu của một nhóm kiến thức:

| Màu | Chủ đề | Ví dụ câu đố |
| --- | --- | --- |
| Xanh lá | Biến, kiểu dữ liệu, `print()` | `x = 5` rồi `x = x + 2`, in ra gì? |
| Vàng | Điều kiện `if / elif / else` | Sắp xếp nhánh để in "Đậu" khi điểm ≥ 5 |
| Tím | Vòng lặp `for / while`, `range()` | Điền `range(?)` để in 0, 1, 2 |
| Xanh dương | Hàm, `return`, tham số | Tìm dòng sai trong hàm tính tổng |

**Chủ đề câu đố = màu chiếm đa số trong hàng vừa đầy** (hòa thì chọn ngẫu nhiên trong các màu hòa).

Vì chỉ được sai một lần, việc đặt khối trở thành chiến thuật: người chơi chủ động "xây" hàng theo chủ đề mình tự tin để an toàn, hoặc né chủ đề mình yếu, và phải trả giá bằng một bố cục lưới khó hơn.

Ở chế độ Luyện tập, hệ thống tăng tần suất khối màu của chủ đề người chơi đang yếu (dựa trên tỉ lệ sai gần nhất), để người học tự nhiên gặp lại phần mình cần ôn.

## 4. Câu đố Rescue

### 4.1. Bốn dạng câu đố (mỗi câu 20–60 giây)

| Dạng | Người chơi làm gì | Validator kiểm tra |
| --- | --- | --- |
| **Sắp xếp (Parsons)** | Kéo 2–4 dòng mã vào đúng thứ tự và đúng mức thụt lề | Cấu trúc AST + đầu ra khớp test case |
| **Điền chỗ trống** | Chọn mảnh mã đúng cho ô trống (có mảnh gây nhiễu) | Chương trình tái tạo cho đầu ra đúng |
| **Đoán đầu ra** | Chọn đầu ra của đoạn mã | So khớp với đầu ra đã tính sẵn |
| **Tìm bug** | Chạm vào token/dòng sai, rồi chọn mảnh thay thế | Mảnh sau khi thay cho đầu ra đúng |

### 4.2. Độ khó tăng theo số hàng dọn cùng lúc

| Số hàng dọn cùng lúc | Câu đố | Điểm gốc |
| --- | --- | --- |
| 1 | 1 bước (điền chỗ trống / đoán đầu ra đơn giản) | 100 |
| 2 | 2–3 mảnh (sắp xếp ngắn, tìm bug 1 dòng) | 250 |
| 3 | Nhiều bước (lồng `if` trong `for`, đoán đầu ra nhiều dòng) | 450 |
| 4+ | Câu đố "Boss": 2 câu liên tiếp cùng chủ đề, phải đúng cả 2 | 700 |

Vì chỉ có một lần trả lời, dọn nhiều hàng một lúc là một quyết định rủi ro thật: điểm cao hơn nhiều nhưng câu đố khó hơn. Người chơi đang ở 🟡 Cảnh báo sẽ phải cân nhắc kỹ trước khi lấp một hàng thứ 3.

Hàng ngang và cột dọc đầy cùng lúc tính chung thành một lần dọn nhiều hàng và dùng **một** câu đố ở mức tương ứng.

Cấp độ của người chơi điều chỉnh tiếp:
- **Beginner:** mảnh mã lớn, nhiều nhất 3 lựa chọn, Hint 1 miễn phí (không giảm điểm).
- **Intermediate:** 4 lựa chọn, có mảnh gây nhiễu theo lỗi thường gặp.
- **Advanced:** ưu tiên dạng Tìm bug và Đoán đầu ra, gợi ý giảm điểm mạnh hơn.

### 4.3. Trong lúc giải câu đố

- Lưới tạm dừng; hàng bị khóa phát sáng phía sau cửa sổ câu đố.
- **Không có đồng hồ bắt buộc** (giữ nguyên nguyên tắc không ép chạy đua tốc độ của hồ sơ). Người chơi có thể suy nghĩ bao lâu tùy ý, vì chỉ có một lần trả lời.
- **Chỉ có 1 lần trả lời.** Nút "Chạy kiểm tra" có bước xác nhận ("Commit câu trả lời này?") để tránh bấm nhầm.
- Gợi ý 3 cấp của AI gia sư dùng được **trước khi trả lời**, bất cứ lúc nào. Gợi ý không khóa quyền hoàn thành, chỉ giảm hệ số điểm (mục 6). Đây là cách người chơi tự bảo vệ mình khi không chắc chắn: đổi điểm lấy an toàn.
- Không có nút bỏ qua câu đố. Mỗi hàng đã đầy bắt buộc phải được giải.

## 5. Thất bại: Bug line, Crash và Last Commit

### 5.1. Sai lần thứ nhất

1. Hàng bị khóa chuyển thành **bug line**: các ô hóa xám, gắn biểu tượng 🐞 và vẫn chiếm chỗ trên lưới.
2. Trạng thái build chuyển sang **🟡 Cảnh báo**.
3. Màn hình hiện **đáp án đúng kèm giải thích ngắn** (AI giải thích dựa trên chẩn đoán của validator, có giải thích soạn sẵn dự phòng). Sau khi đã sai, việc cho xem đáp án là một khoảnh khắc học, không còn là cho đáp án sớm.
4. Bug line ghi nhớ **chủ đề và lỗi** người chơi vừa mắc. Streak về 0.

### 5.2. Sửa bug line (cách duy nhất để lấy lại an toàn)

- Chạm vào bug line để mở **câu đố Debug**: một biến thể của đúng câu vừa sai (cùng khái niệm, khác số liệu hoặc tên biến), luôn ở dạng Tìm bug, 1 lần trả lời.
- Đúng: bug line được dọn, nhận **+150 điểm "Redemption"**, trạng thái trở lại **🟢 Ổn định**, tức là người chơi lại có quyền sai một lần.
- Sai: đó là lần sai thứ hai, **ván kết thúc**.
- Không bắt buộc sửa. Người chơi có thể để bug line nằm đó và chơi tiếp ở trạng thái 🟡.

Debug là một canh bạc có chủ đích: sửa thì lấy lại an toàn và dọn được chỗ trên lưới, nhưng sai là thua. Người chơi phải tự đánh giá mình đã thật sự hiểu lỗi vừa mắc chưa, và đó chính là kỹ năng mà game muốn rèn.

Bom không xóa được ô bug. Cách duy nhất để xóa bug line là sửa nó.

### 5.3. Điều kiện thua

| Điều kiện | Kết quả |
| --- | --- |
| **Sai lần thứ hai** trong ván (câu đố Rescue hoặc Debug) | **SYSTEM CRASH**: thua ván ngay |
| Không khối nào trong khay đặt vừa lưới | **GAME OVER**, có cơ hội Last Commit (mục 5.4) |

### 5.4. Last Commit (một lần mỗi ván, chỉ khi hết chỗ đặt khối)

Khi lưới không còn chỗ cho bất kỳ khối nào, người chơi được đề nghị **một câu đố "Last Commit"**:
- Độ khó tương đương câu đố 3 hàng, 1 lần trả lời, chủ đề là chủ đề người chơi sai nhiều nhất trong ván (hoặc ngẫu nhiên nếu chưa sai lần nào).
- Đúng: xóa 3 hàng nhiều ô nhất (không tính bug line) và ván chơi tiếp tục.
- Sai hoặc bỏ qua: kết thúc ván.

Last Commit **không** cứu được ván khi đã sai lần thứ hai. Luật "chỉ được sai 1 lần" luôn giữ nguyên.

### 5.5. Màn hình kết thúc ván

Cho thấy điểm, chuỗi streak dài nhất, số bug đã sửa và **"Báo cáo lỗi"**: hai câu đã sai, khái niệm liên quan (ví dụ: "range() không gồm giá trị kết thúc") kèm nút **"Luyện lại chủ đề này"** mở thẳng chế độ Luyện tập với chủ đề đó. Người chơi rời ván với một việc cụ thể để làm tiếp, thay vì chỉ thấy chữ "thua".

## 6. Tính điểm

```
Điểm dọn hàng = Điểm gốc × Hệ số gợi ý × Hệ số streak
```

| Thành phần | Giá trị |
| --- | --- |
| Điểm gốc | 100 / 250 / 450 / 700 theo số hàng (mục 4.2) |
| Hệ số gợi ý (lấy theo cấp cao nhất đã xem) | Không dùng: ×1.0 · Hint 1: ×0.9 · Hint 2: ×0.75 · Hint 3: ×0.5 |
| Streak "Clean Build" (đúng mà không dùng gợi ý, liên tiếp) | 1: ×1.0 · 2: ×1.2 · 3–4: ×1.5 · 5+: ×2.0 |
| Đặt khối | +1 điểm mỗi ô |
| Sửa bug line | +150 cố định |

**Ví dụ:** dọn 2 hàng, đúng, đã xem Hint 2: 250 × 0.75 × 1.0 (dùng gợi ý nên streak về 0) = **188 điểm**.
Dọn 2 hàng, đúng, không gợi ý, streak đang 3: 250 × 1.0 × 1.5 = **375 điểm**.

Chênh lệch này khuyến khích tự suy nghĩ trước khi xem gợi ý, nhưng gợi ý luôn là lựa chọn an toàn hợp lệ.

## 7. Vật phẩm hỗ trợ

Vật phẩm chỉ giúp việc **xếp khối**, không bao giờ cho thêm lượt sai, để luật "chỉ được sai 1 lần" luôn rõ ràng.

| Vật phẩm | Tác dụng | Cách nhận |
| --- | --- | --- |
| 💣 Bom | Xóa vùng 3×3 (trừ ô bug), không tính điểm cho ô bị xóa | Streak 3 |
| 🔀 Xáo khối | Đổi 3 khối trong khay | Streak 5 |
| ↩️ Hoàn tác | Hủy lần đặt khối gần nhất, **trước khi** hàng bị khóa (giúp tránh lấp một hàng có chủ đề mình yếu) | Dọn 4+ hàng một lần |
| 🔍 Debugger | Câu đố tiếp theo được xem Hint 2 mà không giảm điểm | Sửa 1 bug line |

## 8. Chế độ chơi

| Chế độ | Khác biệt | Dùng cho |
| --- | --- | --- |
| **Rescue (mặc định)** | Toàn bộ luật ở trên: 1 lần trả lời, sai 2 lần là thua | Trải nghiệm chính, tính điểm |
| **Luyện tập** | Không thua: mỗi câu có 3 lần trả lời, bug line tự biến mất sau 5 lượt, không tính điểm xếp hạng | Người mới, người dễ áp lực, nhóm đối chứng khi pilot |

Có chế độ Luyện tập để giữ mục tiêu "ít áp lực" của hồ sơ, đồng thời cho nhóm dữ liệu so sánh: có hình phạt thì người học có suy nghĩ kỹ hơn hay bỏ cuộc sớm hơn?

## 9. Ví dụ một ván

1. Hàng 5 có 6 ô tím và 2 ô xanh lá. Người chơi đặt khối chữ L để lấp nốt, hàng 5 đầy và bị khóa. Chủ đề: vòng lặp.
2. Câu đố (Điền chỗ trống): `for i in range(___): print(i)`, đầu ra mong đợi `0 1 2`. Lựa chọn: `2`, `3`, `4`.
3. Người chơi không chắc, xem Hint 1: *"range() dừng trước giá trị kết thúc."* Chọn `3`: đúng. Được 100 × 0.9 = **90 điểm**.
4. Vài lượt sau, hàng 2 (vàng, chủ đề điều kiện) đầy. Người chơi tự tin, không xem gợi ý, chọn sai. Hàng 2 thành bug line 🐞, trạng thái 🟡 Cảnh báo, màn hình giải thích vì sao `elif` không chạy khi `if` đã đúng.
5. Người chơi đọc kỹ giải thích, rồi chạm vào bug line. Câu đố Debug: cùng khái niệm `if/elif`, khác số liệu. Đúng: hàng 2 được dọn, +150, trạng thái trở lại 🟢.
6. Nếu ở bước 5 người chơi sai: System Crash, ván kết thúc, Báo cáo lỗi hiện khái niệm `if/elif` với nút "Luyện lại chủ đề này".

## 10. Ngân hàng câu đố: mẫu có tham số, sinh sẵn và kiểm chứng trước

### 10.1. Vấn đề

Một ván dài có 15–30 câu đố, cộng thêm câu đố Debug phải là *biến thể* của câu vừa sai. 10–15 câu đố cố định sẽ lặp lại ngay trong ván đầu tiên, và người chơi sẽ nhớ đáp án thay vì hiểu khái niệm. Với luật chỉ được sai 1 lần, mỗi câu đố còn phải **không thể mơ hồ**: nếu có hai đáp án cùng đúng, người chơi thua oan.

### 10.2. Giải pháp: 16 mẫu × nhiều biến thể, sinh trước khi phát hành

**Mẫu (template)** là một câu đố có chỗ trống cho tham số. Nhóm viết tay **16 mẫu = 4 chủ đề × 4 dạng câu đố**. Mỗi mẫu gồm:

- Khung mã có tham số (số, tên biến, chuỗi, toán tử).
- Miền giá trị và ràng buộc cho từng tham số.
- **Danh sách lỗi thường gặp** dùng để sinh mảnh gây nhiễu (lệch một đơn vị, thiếu dấu hai chấm, sai thụt lề, in sai biến...). Mỗi lỗi gắn với một nhóm lỗi của validator, nên gợi ý soạn sẵn và giải thích sau khi sai đã có sẵn cho từng lỗi.
- Gợi ý soạn sẵn 3 cấp cho mẫu.
- Mức độ (1, 2 hoặc 3 hàng) và cấp độ người chơi phù hợp.

Ví dụ một mẫu:

```yaml
id: loop_range_fill_01
chu_de: vong_lap
dang: dien_cho_trong
muc_do: 1
khung: |
  for {bien} in range({a}, ___):
      print({bien})
tham_so:
  bien: [i, j, k, n, so]
  a:    [0, 1, 2]
  dem:  [2, 3, 4]          # số lần lặp
dap_an: "{a} + {dem}"      # giá trị kết thúc đúng
dau_ra: "range({a}, {a}+{dem})"  # validator tự tính bằng cách chạy chương trình
loi_gay_nhieu:
  - lech_mot_thieu: "{a} + {dem} - 1"   # nhóm lỗi: đầu ra không khớp (thiếu một lần)
  - lech_mot_thua:  "{a} + {dem} + 1"   # nhóm lỗi: đầu ra không khớp (thừa một lần)
goi_y:
  - "range() dừng trước giá trị kết thúc."
  - "Đếm xem cần bao nhiêu số được in ra."
  - "Giá trị kết thúc = số bắt đầu + số lần lặp."
```

Mẫu này cho 5 × 3 × 3 = 45 biến thể khác nhau.

**Sinh sẵn, không sinh lúc chơi.** Một script chạy offline:
1. Sinh khoảng 30–50 biến thể cho mỗi mẫu (tổng khoảng 500–800 câu đố).
2. Validator chạy **đáp án đúng** của từng biến thể và ghi lại đầu ra mong đợi.
3. Validator chạy **từng mảnh gây nhiễu** và loại bỏ biến thể nếu một mảnh gây nhiễu tình cờ cũng cho đầu ra đúng (câu đố mơ hồ).
4. Loại bỏ các biến thể trùng đầu ra, hoặc có đầu ra quá dài để hiển thị trên điện thoại.
5. Lưu các biến thể đạt vào SQLite, kèm mẫu gốc, mức độ và nhóm lỗi của từng mảnh gây nhiễu.
6. Thành viên phụ trách nội dung rà soát ngẫu nhiên khoảng 10% mỗi mẫu bằng checklist.

Lúc chơi, game chỉ **chọn** câu đố từ ngân hàng đã kiểm chứng: không có mã nào được tạo hay chạy mới, AI không tham gia tạo đề hay chấm điểm. Điều này giữ nguyên nguyên tắc an toàn của hồ sơ.

### 10.3. Chọn câu đố trong ván

- Lọc theo chủ đề (màu hàng), mức độ (số hàng dọn) và cấp độ người chơi.
- Không dùng lại một mẫu trong 3 câu đố gần nhất; không bao giờ lặp lại một biến thể đã gặp trong ván.
- **Câu đố Debug** = cùng mẫu với câu vừa sai, biến thể khác, ở dạng Tìm bug. Người chơi gặp lại đúng khái niệm, không gặp lại đúng đáp án.
- Lưu biến thể đã gặp theo người chơi để các ván sau ưu tiên biến thể mới.

### 10.4. Vì sao cách này phù hợp với MVP

| | 10–15 câu cố định | 16 mẫu sinh sẵn |
| --- | --- | --- |
| Công viết nội dung | 10–15 câu | 16 mẫu (mỗi mẫu tốn công hơn một câu, nhưng không nhiều hơn bao nhiêu) |
| Số câu đố trong ngân hàng | 10–15 | ~500–800 đã kiểm chứng |
| Lặp lại trong ván | Ngay ván đầu | Gần như không |
| Biến thể cho câu đố Debug | Không có | Có sẵn |
| Kiểm tra câu đố mơ hồ | Rà tay | Validator tự loại, người rà mẫu |
| Rủi ro an toàn | Thấp | Thấp như nhau: không tạo mã lúc chơi |

Lộ trình: **tuần 1** viết 16 mẫu (thay cho 10–15 câu đố); **tuần 2–3** viết script sinh biến thể và chạy kiểm chứng cùng lúc với validator, vì script dùng chính validator đó. Nếu thiếu thời gian, có thể bắt đầu với 8 mẫu (2 dạng cho mỗi chủ đề) và bổ sung sau.

Về sau (giai đoạn 2), AI có thể giúp **soạn nháp mẫu mới** để giảng viên rà soát và duyệt, nhưng vẫn không tham gia lúc chơi.

## 11. Ảnh hưởng tới kỹ thuật và dữ liệu pilot

- **Validator:** thêm thao tác chạy đáp án/mảnh gây nhiễu cho script sinh biến thể (offline). Phạm vi Python được hỗ trợ không đổi.
- **Frontend:** thêm trạng thái hàng `locked` và `bug`, cửa sổ câu đố có bước xác nhận, chỉ báo trạng thái build 🟢🟡🔴, màn Báo cáo lỗi.
- **Dữ liệu pilot mới thu được:** tỉ lệ đúng theo chủ đề và theo mẫu, tỉ lệ dùng gợi ý trước khi trả lời, tỉ lệ dám sửa bug line và tỉ lệ sửa thành công, chủ đề hay bị né (qua cách đặt khối màu), độ dài trung bình một ván, tỉ lệ quay lại sau khi thua so với chế độ Luyện tập.

## 12. Các chỗ cần sửa trong hồ sơ

Các câu dưới đây trong hồ sơ hiện tại **ghi rõ là Code Rescue** (không phải Syntax Rows), nên cần sửa để khớp luật mới:

| Vị trí | Hiện tại | Sửa thành |
| --- | --- | --- |
| Trang 2, đoạn 2 | "khi lưới đầy dần, người chơi giải một câu đố mã ngắn để nhận vật phẩm hỗ trợ như bom, xáo khối hoặc hoàn tác" | "mỗi khi một hàng đầy, người chơi giải một câu đố mã ngắn để dọn hàng và nhận điểm; cả ván chỉ được sai một lần" |
| Trang 3, mục I | "khi lưới đầy dần, một câu đố mã ngắn xuất hiện ... Nếu đạt, họ nhận vật phẩm hỗ trợ" | Mô tả vòng chơi khóa hàng, giải đố, dọn hàng hoặc bug line (mục 2 ở trên) |
| Trang 4, quy tắc gameplay thứ 2 | "Ở lớp Code Rescue, câu đố mã không quyết định bố cục lưới ... một lỗi mã không làm người chơi thua ván." | "Ở lớp Code Rescue, hàng đầy chỉ được dọn khi người chơi giải đúng câu đố, mỗi câu một lần trả lời. Lần sai đầu tiên để lại một bug line có thể sửa; lần sai thứ hai kết thúc ván. Chế độ Luyện tập không có điều kiện thua." |
| Trang 4, quy tắc gameplay thứ 3 | "Người chơi vẫn được thử lại" | "Ở Syntax Rows và chế độ Luyện tập, người chơi được thử lại; ở Code Rescue, gợi ý dùng được trước khi trả lời và chỉ giảm điểm." |
| Trang 4, bảng bước 05 | "nhận vật phẩm hỗ trợ (Code Rescue)" | "dọn hàng và tính điểm theo gợi ý và streak (Code Rescue)" |
| Trang 2 & 9, phạm vi MVP và lộ trình tuần 1 | "10-15 câu đố" | "16 mẫu câu đố có tham số (~500 biến thể do validator kiểm chứng trước)" |
| Trang 6, "Hai lớp chơi" | "Code Rescue giữ trải nghiệm xếp khối quen thuộc và bảo đảm luôn có một game chơi được" | "Code Rescue gắn mỗi lần dọn hàng với một câu đố mã, chỉ được sai một lần; chế độ Luyện tập bảo đảm luôn có một phiên bản ít áp lực" |
