import requests
import json
import os
import time
from datetime import datetime

STUDIO_ID = "33509364"
API_BASE = f"https://api.scratch.mit.edu/studios/{STUDIO_ID}/comments"
DB_FILE = "database.json"

# Load database
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

# Save database
def save_db(db):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

# Khởi tạo user mới
def init_user(username):
    return {
        "score": 100,
        "tier": "Danh tiếng xuất sắc",
        "last_active_date": None,
        "active_days_count": 0,
        "processed_comments": [] # Tránh xử lý lặp 1 bình luận
    }

# Cập nhật hạng (Tier) dựa trên điểm
def update_tier(score):
    if score >= 90: return "Danh tiếng xuất sắc"
    elif score >= 30: return "Danh tiếng tốt"
    else: return "Danh tiếng kém"

# Xử lý API
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

def process_comment(comment, db):
    comment_id = comment["id"]
    author = comment["author"]["username"]
    content = comment["content"]
    
    # Lấy ngày hiện tại (YYYY-MM-DD)
    date_str = comment["datetime_created"][:10] 

    if author not in db:
        db[author] = init_user(author)

    # 1. Cập nhật ngày hoạt động
    if db[author]["last_active_date"] != date_str:
        db[author]["last_active_date"] = date_str
        db[author]["active_days_count"] += 1
        
        # Cộng 10 điểm nếu đủ 7 ngày hoạt động
        if db[author]["active_days_count"] >= 7:
            db[author]["score"] = min(100, db[author]["score"] + 10)
            db[author]["active_days_count"] = 0 # Reset lại bộ đếm
            print(f"Tăng 10 điểm cho {author} vì hoạt động 7 ngày.")

    # 2. Bỏ qua nếu comment đã được xử lý (tránh trừ điểm nhiều lần)
    if comment_id in db[author].get("processed_comments", []):
        return
    
    # 3. Phân tích nội dung (Có thể mở rộng tùy ý)
    # Ví dụ hệ thống quét lệnh quản trị từ Ban Quản Lý (vd: "/tru 20 @user123 lach luat")
    # Bạn có thể tự viết thêm regex hoặc bộ lọc từ ngữ (NLP) ở đây.

    # Đảm bảo điểm nằm trong khoảng 0-100
    db[author]["score"] = max(0, min(100, db[author]["score"]))
    db[author]["tier"] = update_tier(db[author]["score"])
    
    # Lưu lại id comment đã xử lý (giữ 100 ID gần nhất để file không bị quá nặng)
    db[author].setdefault("processed_comments", []).append(comment_id)
    db[author]["processed_comments"] = db[author]["processed_comments"][-100:]

def main():
    db = load_db()
    comments = fetch_comments()
    
    print(f"Đã lấy {len(comments)} bình luận gốc.")

    for comment in comments:
        process_comment(comment, db)
        
        # Nếu có phản hồi, gọi API lấy thêm phản hồi
        if comment.get("reply_count", 0) > 0:
            time.sleep(0.5) # Nghỉ 0.5s để tránh bị Scratch khóa IP (Rate Limit)
            replies = fetch_replies(comment["id"])
            for reply in replies:
                process_comment(reply, db)

    save_db(db)
    print("Hoàn tất cập nhật CSDL.")

if __name__ == "__main__":
    main()