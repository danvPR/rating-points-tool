import requests
import json
import os
import time
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

STUDIO_ID = "33509364"
API_BASE = f"https://api.scratch.mit.edu/studios/{STUDIO_ID}/comments"
DB_FILE = "database.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except: return {}
    return {}

def save_db(db):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

def init_user(username):
    return {
        "score": 100,
        "tier": "Danh tiếng xuất sắc",
        "last_active_date": "",
        "active_days_count": 0,
        "total_deducted": 0,
        "recent_comment": "",
        "processed_comments": []
    }

def update_tier(score):
    if score >= 90: return "Danh tiếng xuất sắc"
    elif score >= 30: return "Danh tiếng tốt"
    else: return "Danh tiếng kém"

def fetch_comments():
    try:
        response = requests.get(f"{API_BASE}?offset=0&limit=40", timeout=10)
        return response.json()
    except Exception as e:
        print(f"Lỗi lấy comments: {e}")
        return []

def fetch_replies(comment_id):
    try:
        response = requests.get(f"{API_BASE}/{comment_id}/replies", timeout=10)
        return response.json()
    except Exception as e:
        print(f"Lỗi lấy replies cho {comment_id}: {e}")
        return []

# 1. KẾT NỐI GOOGLE SHEETS
def get_google_sheet():
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    sheet_url = os.environ.get('SHEET_URL')
    if not creds_json or not sheet_url:
        return None
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_url(sheet_url).sheet1

# 2. ĐỌC DỮ LIỆU TỪ SHEETS VÀO DATABASE (Ưu tiên điểm số từ Sheets)
def sync_from_sheet(db, sheet):
    all_values = sheet.get_all_values()
    # Nếu sheet chưa có đủ 3 hàng (Banner + Tiêu đề), bỏ qua
    if len(all_values) <= 3:
        return all_values 
    
    data_rows = all_values[3:] # Dữ liệu bắt đầu từ hàng 4 (index 3)
    for row in data_rows:
        if not row or not row[0].strip(): continue
        username = row[0].strip()
        
        # Bù thêm cột trống nếu mảng ngắn hơn 7 cột (A đến G)
        while len(row) < 7: row.append("")
        
        if username not in db:
            db[username] = init_user(username)
        
        # Luôn lấy Điểm và Điểm Trừ trên Sheets làm gốc
        score_str = row[1].strip()
        db[username]["score"] = int(score_str) if score_str.isdigit() else 100
        
        deducted_str = row[2].strip()
        db[username]["total_deducted"] = int(deducted_str) if deducted_str.isdigit() else 0
        
        # Cập nhật thứ hạng
        db[username]["tier"] = update_tier(db[username]["score"])

    return all_values

def process_comment(comment, db):
    comment_id = comment["id"]
    author = comment["author"]["username"]
    content = comment["content"]
    date_str = comment["datetime_created"][:10] 

    if author not in db:
        db[author] = init_user(author)

    # Nếu bình luận đã xử lý rồi -> Bỏ qua ngay lập tức để không cập nhật lại nội dung
    if comment_id in db[author].get("processed_comments", []):
        return

    # Tính ngày hoạt động để cộng điểm
    if db[author].get("last_active_date") != date_str:
        db[author]["last_active_date"] = date_str
        db[author]["active_days_count"] = db[author].get("active_days_count", 0) + 1
        
        if db[author]["active_days_count"] >= 7:
            db[author]["score"] = min(100, db[author]["score"] + 10)
            db[author]["active_days_count"] = 0
            print(f"Tăng 10 điểm cho {author} vì hoạt động đủ 7 ngày.")
    
    # Ghi nhận bình luận mới (sẽ đẩy lên Sheets)
    db[author]["recent_comment"] = content
    db[author]["tier"] = update_tier(db[author]["score"])
    
    # Đánh dấu đã quét
    db[author].setdefault("processed_comments", []).append(comment_id)
    db[author]["processed_comments"] = db[author]["processed_comments"][-100:]

# 3. GHI NGƯỢC LẠI LÊN SHEETS (Giữ nguyên Cột Lịch Sử và Cột Log)
def sync_to_sheet(db, sheet, all_values):
    if len(all_values) > 3:
        data_rows = all_values[3:]
    else:
        data_rows = []
        
    new_data_rows = []
    existing_usernames = set()
    
    # Cập nhật danh sách cũ
    for row in data_rows:
        if not row or not row[0].strip(): continue
        username = row[0].strip()
        existing_usernames.add(username)
        while len(row) < 7: row.append("")
        
        user_data = db.get(username)
        if user_data:
            row[1] = str(user_data["score"])
            row[2] = str(user_data.get("total_deducted", 0))
            # Cột 3 (Index 3 - Lịch sử) -> GIỮ NGUYÊN
            row[4] = user_data.get("last_active_date", "")
            # Cột 5 (Index 5 - Log) -> GIỮ NGUYÊN
            
            # Cột 6: Bình luận. Chỉ ghi nếu có bình luận mới. Nếu không có giữ nguyên bình luận cũ
            if user_data.get("recent_comment"):
                row[6] = user_data["recent_comment"]
                user_data["recent_comment"] = "" # Xóa biến tạm sau khi đã ghi

        new_data_rows.append(row)
        
    # Thêm người dùng mới tinh vào cuối danh sách
    for username, user_data in db.items():
        if username not in existing_usernames:
            new_row = [
                username,
                str(user_data["score"]),
                str(user_data.get("total_deducted", 0)),
                "", # Lịch sử (Trống)
                user_data.get("last_active_date", ""),
                "", # Log (Trống)
                user_data.get("recent_comment", "")
            ]
            user_data["recent_comment"] = ""
            new_data_rows.append(new_row)
            
    # Đẩy lên Sheets bắt đầu từ hàng A4, giữ nguyên format màu sắc của bạn
    if new_data_rows:
        sheet.update(values=new_data_rows, range_name='A4', value_input_option='USER_ENTERED')
        print("Đồng bộ Sheets thành công! Bảo toàn định dạng.")

def main():
    db = load_db()
    sheet = None
    all_values = []

    # BƯỚC 1: Lấy dữ liệu từ Sheets
    try:
        sheet = get_google_sheet()
        if sheet:
            print("Đang đọc dữ liệu từ Google Sheets...")
            all_values = sync_from_sheet(db, sheet)
    except Exception as e:
        print(f"Lỗi đọc Google Sheets: {e}")

    # BƯỚC 2: Quét Scratch
    comments = fetch_comments()
    print(f"Đã lấy {len(comments)} bình luận gốc.")

    for comment in comments:
        process_comment(comment, db)
        if comment.get("reply_count", 0) > 0:
            time.sleep(0.5)
            replies = fetch_replies(comment["id"])
            for reply in replies:
                process_comment(reply, db)

    # BƯỚC 3: Ghi lại lên Sheets và lưu file JSON
    if sheet:
        try:
            sync_to_sheet(db, sheet, all_values)
        except Exception as e:
            print(f"Lỗi ghi Google Sheets: {e}")

    save_db(db)
    print("Hoàn tất quá trình.")

if __name__ == "__main__":
    main()