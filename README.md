# 🚀 SCRATCH STUDIO MODERATOR & ANALYTICS ![Version](https://img.shields.io/badge/version-1.1.0-blue.svg) ![License](https://img.shields.io/badge/license-All_Rights_Reserved-red)

Đây là một công cụ tự động (Bot API) được phát triển bằng Python nhằm mục đích quản lý, giám sát hoạt động và tự động kiểm duyệt nội dung của các thành viên trong một Studio cụ thể trên nền tảng Scratch. Hệ thống tự động chấm điểm phạt, tính điểm thưởng chuyên cần và đồng bộ hóa dữ liệu trực tiếp lên đám mây thông qua Google Sheets.

## 📋 Mục lục
- [Tính năng](#-tính-năng)
- [Cơ chế hoạt động](#-cơ-chế-hoạt-động)
- [Các thông số cấu hình cứng lưu ý](#-các-thông-số-cấu-hình-cứng-lưu-ý)
- [Yêu cầu hệ thống](#-yêu-cầu-hệ-thống)
- [Cài đặt](#-cài-đặt)
- [Cấu hình file Từ Cấm](#-cấu-hình-file-từ-cấm)
- [Cấu hình môi trường](#-cấu-hình-môi-trường)
- [Cấu trúc bảng tính Google Sheets](#-cấu-trúc-bảng-tính-google-sheets)
- [Thiết lập chạy tự động hóa](#-thiết-lập-chạy-tự-động-hóa)
- [Giấy phép](#-giấy-phép)

---

## ✨ Tính năng
* **Quét dữ liệu đa nguồn:** Tự động thu thập toàn bộ bình luận, phản hồi (replies), danh sách dự án mới tải lên và nhật ký hoạt động trong Studio Scratch.
* **Bộ lọc từ cấm thông minh:** Kiểm duyệt nội dung bình luận bằng biểu thức chính quy (Regex `\bword\b`), giúp nhận diện chính xác từ nhạy cảm mà không bị bắt nhầm các từ chứa ký tự tương đồng (Ví dụ: cấm từ "cá" không bị phạt nhầm từ "cát").
* **Giới hạn spam dự án:** Tự động phát hiện và xử lý trừ điểm thẳng tay đối với các thành viên đăng tải quá 5 dự án trong vòng một ngày (phạt 5 điểm khi vừa chạm mốc dự án thứ 6).
* **Hệ thống phần thưởng chuyên cần:** Tự động theo dõi số ngày hoạt động và cộng điểm thưởng (hoặc giảm trừ 10 điểm phạt cũ) khi thành viên tích lũy đủ mốc 30 ngày tương tác.
* **Đồng bộ hóa 2 chiều:** Đọc thông tin thành viên hiện tại từ Google Sheets, sau đó xử lý dữ liệu rồi tự động cập nhật ngược lại theo thời gian thực.

---

## ⚙️ Cơ chế hoạt động

```
[Scratch API] ──> [Bộ lọc Từ Cấm / Kiểm Tra Số Dự Án] ──> [Cập nhật Local database.json] ──> [Đồng bộ lên Google Sheets (A5:E)]
```

Hệ thống hoạt động theo vòng lặp tuần tự:
1. Đọc dữ liệu thô từ file cục bộ `database.json`. File này đóng vai trò là bộ nhớ đệm (Cache) để lưu trữ tối đa 100 ID đã xử lý gần nhất, giúp bot tránh trùng lặp dữ liệu khi chạy lại.
2. Kết nối tới Google Sheets thông qua tài khoản dịch vụ (Service Account) để đồng bộ danh sách thành viên.
3. Gửi yêu cầu HTTPS tới Scratch API để lấy tối đa 40 hoạt động, dự án và bình luận mới nhất.
4. Phân tích nội dung, áp dụng thuật toán tính điểm thưởng/phạt.
5. Đẩy toàn bộ dữ liệu mới cập nhật (Log phạt, bình luận, ngày hoạt động) lên lại Google Sheets từ ô dữ liệu **A5** trở đi.

---

## ⚠️ Các thông số cấu hình cứng lưu ý

Trước khi chạy mã nguồn, bạn cần lưu ý kiểm tra và chỉnh sửa hai thông số được đặt cố định (hardcoded) trong file `main.py` để phù hợp với Studio của bạn:
* **`STUDIO_ID`**: Hiện tại đang mặc định là `"33509364"`. Hãy đổi thành ID Studio Scratch của bạn.
* **ID Sheet con (GID)**: Trong hàm `get_google_sheet()`, hệ thống đang gọi đích danh Sheet có ID là `1060874817` (`get_worksheet_by_id(1060874817)`). Hãy đảm bảo Google Sheets của bạn chứa Sheet con có GID tương ứng, hoặc sửa lại số GID này trong code.

---

## 📋 Yêu cầu hệ thống
* **Python 3.8+**
* Tài khoản Google Cloud để tạo **Service Account** (Lấy file cấu hình Credentials JSON)
* Một đường dẫn URL của Google Sheets và quyền chia sẻ (Editor) cho email của Service Account.

---

## 🛠 Cài đặt

1. Clone mã nguồn về máy:
   ```bash
   git clone https://github.com/danvPR/scratch-api-fetching-danv.git
   cd scratch-api-fetching-danv
   ```

2. Cài đặt các thư viện cần thiết:
   ```bash
   pip install requests gspread google-auth
   ```

---

## 📝 Cấu hình file Từ Cấm (`censorship-badwr.txt`)

Tạo một file văn bản tên là `censorship-badwr.txt` nằm cùng thư mục với file `main.py`.
* Định dạng file phải là mã hóa **UTF-8**.
* Mỗi dòng là một từ hoặc cụm từ cần đưa vào danh sách đen.
* Nhờ cơ chế ranh giới từ của Regex, bot sẽ bắt chính xác từ độc lập trong câu (Ví dụ: Chặn từ `ngốc` thì bình luận `"bạn ngốc thế"` sẽ bị gắn thẻ vi phạm, nhưng từ `"ngốc xếch"` viết liền sẽ không bị phạt nhầm).

---

## 🔐 Cấu hình môi trường (Environment Variables)

Hệ thống lấy thông tin cấu hình bảo mật thông qua biến môi trường nhằm đảm bảo an toàn dữ liệu. Bạn cần cấu hình 2 biến sau:
* `GOOGLE_CREDENTIALS`: Toàn bộ nội dung chuỗi JSON của file Google Service Account Credentials.
* `SHEET_URL`: Đường dẫn URL đầy đủ trỏ tới bảng tính Google Sheets cần đồng bộ.

---

## 📊 Cấu trúc bảng tính Google Sheets

Dữ liệu được ghi đè từ dòng số **5** (Ô A5) với định dạng 5 cột như sau:

| Cột | Tên trường | Mô tả nội dung dữ liệu được đồng bộ |
|---|---|---|
| **Cột A** | **User** | Tên tài khoản (Username) của thành viên trên Scratch. |
| **Cột B** | **Hoạt động** | Danh sách các ngày mà thành viên đó có phát sinh hoạt động tương tác. |
| **Cột C** | **Cmt** | Mốc thời gian (Ngày) của bình luận cuối cùng do thành viên đó đăng tải. |
| **Cột D** | **Log** | Lịch sử ghi nhận biến động điểm (Ví dụ: các dòng thông báo phạt spam, thưởng chuyên cần). |
| **Cột E** | **Chi tiết Cmt** | Tổng hợp nội dung các bình luận mà thành viên đã gõ (Có đánh dấu `[⚠ TỪ CẤM]` nếu vi phạm). |

---

## 🚀 Thiết lập chạy tự động hóa (Automation)

Vì mã nguồn hoạt động theo cơ chế quét một lần rồi tắt, bạn cần thiết lập cơ chế chạy lặp lại tự động để hệ thống hoạt động như một con bot thực thụ.

### Cách 1: Dùng GitHub Actions (Miễn phí, tối ưu nhất)
Tạo file cấu hình tại đường dẫn `.github/workflows/run_bot.yml` trong kho lưu trữ của bạn:
```yaml
name: Run Scratch Bot
on:
  schedule:
    - cron: '*/15 * * * *' # Tự động chạy lại mỗi 15 phút một lần
  workflow_dispatch:
jobs:
  run-bot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: pip install requests gspread google-auth
      - name: Run Bot
        env:
          GOOGLE_CREDENTIALS: ${{ secrets.GOOGLE_CREDENTIALS }}
          SHEET_URL: ${{ secrets.SHEET_URL }}
        run: python main.py
```

### Cách 2: Sử dụng Cronjob trên Linux/VPS
Mở trình cấu hình cron bằng lệnh `crontab -e` và thêm dòng sau để bot chạy mỗi 15 phút:
```bash
*/15 * * * * cd /path/to/scratch-api-fetching-danv && python3 main.py >> bot.log 2>&1
```

---

## ⚖️ Giấy phép

Copyright (c) 2026 danvPR.

**All Rights Reserved.**

Toàn bộ mã nguồn, tài liệu và các file liên quan thuộc bản quyền của tác giả. Nghiêm cấm mọi hành vi sao chép, phân phối lại, chỉnh sửa hoặc sử dụng cho mục đích thương mại khi chưa có sự cho phép bằng văn bản từ chủ sở hữu bản quyền.
