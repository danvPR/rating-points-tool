import requests
import json
import os
import time
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

STUDIO_ID = "33509364"
API_BASE = f"https://api.scratch.mit.edu/studios/{STUDIO_ID}/comments"
PROJECTS_API = f"https://api.scratch.mit.edu/studios/{STUDIO_ID}/projects"
DB_FILE = "database.json"

BANNED_WORDS = ["chửi bậy", "ngu", "18+", "scam"] 

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except: return {}
    return {}

def save_db(db):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

def update_tier(score):
    if score >= 90: return "XS"
    elif score >= 30: return "Tốt"
    else: return "Kém"

def init_user(username):
    return {
        "score": 100,
        "tier": "XS",
        "last_active_date": "",
        "active_days_count": 0,
        "total_deducted": 0,
        "new_comments": [], 
        "new_logs": [], 
        "processed_comments": [],
        "processed_projects": [],
        "projects_today": 0,
        "last_project_date": ""
    }

def fetch_comments():
    try: return requests.get(f"{API_BASE}?offset=0&limit=40", timeout=10).json()
    except: return []

def fetch_replies(comment_id):
    try: return requests.get(f"{API_BASE}/{comment_id}/replies", timeout=10).json()
    except: return []

def fetch_projects():
    try: return requests.get(f"{PROJECTS_API}?offset=0&limit=40", timeout=10).json()
    except: return []

# KẾT NỐI SHEETS
def get_google_sheet():
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    sheet_url = os.environ.get('SHEET_URL')
    if not creds_json or not sheet_url: return None
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_url(sheet_url).sheet1

def sync_from_sheet(db, sheet):
    all_values = sheet.get_all_values()
    if len(all_values) <= 3: return all_values 
    
    data_rows = all_values[3:]
    for row in data_rows:
        if not row or not row[0].strip(): continue
        username = row[0].strip()
        while len(row) < 7: row.append("")
        
        if username not in db: db[username] = init_user(username)
        
        score_str = row[1].strip()
        db[username]["score"] = int(score_str) if score_str.isdigit() else 100
        
        deducted_str = row[2].strip()
        db[username]["total_deducted"] = int(deducted_str) if deducted_str.isdigit() else 0
        db[username]["tier"] = update_tier(db[username]["score"])
    return all_values

# XỬ LÝ BÌNH LUẬN VÀ LƯU DƯỚI DẠNG ID
def process_comment(comment, db):
    comment_id = str(comment["id"])
    author = comment["author"]["username"]
    content = comment["content"]
    date_str = comment["datetime_created"][:10] 

    if author not in db: db[author] = init_user(author)
    if comment_id in db[author].get("processed_comments", []): return

    if db[author].get("last_active_date") != date_str:
        db[author]["last_active_date"] = date_str
        db[author]["active_days_count"] = db[author].get("active_days_count", 0) + 1
        if db[author]["active_days_count"] >= 7:
            db[author]["score"] = min(100, db[author]["score"] + 10)
            db[author]["active_days_count"] = 0
            
    content_lower = content.lower()
    is_banned = any(word.lower() in content_lower for word in BANNED_WORDS)
    tag = "[⚠️ TỪ CẤM] " if is_banned else ""
    
    # Định dạng mới: ID (Nội dung) thay vì Link dài dòng
    formatted_comment = f"{tag}{comment_id} ({content})"
    
    # Kèm thêm ID vào một biến ẩn để lát nữa kiểm tra trùng lặp trên Sheet
    db[author].setdefault("new_comments", []).append({
        "id": comment_id,
        "text": formatted_comment
    })
    
    db[author]["tier"] = update_tier(db[author]["score"])
    db[author].setdefault("processed_comments", []).append(comment_id)
    db[author]["processed_comments"] = db[author]["processed_comments"][-100:]

def process_project(project, db):
    author = project.get("username", project.get("creator"))
    if not author: return
    author = str(author)
    proj_id = str(project["id"])
    
    if author not in db: db[author] = init_user(author)
    if proj_id in db[author].get("processed_projects", []): return

    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    if db[author].get("last_project_date") != today_str:
        db[author]["last_project_date"] = today_str
        db[author]["projects_today"] = 0
        
    db[author]["projects_today"] += 1
    
    if db[author]["projects_today"] > 5:
        db[author]["score"] -= 5
        db[author]["total_deducted"] += 5
        db[author]["tier"] = update_tier(db[author]["score"])
        log_msg = f"[{today_str}] ⚠️ Đăng quá 5 dự án (-5đ)"
        db[author].setdefault("new_logs", []).append(log_msg)

    db[author].setdefault("processed_projects", []).append(proj_id)
    db[author]["processed_projects"] = db[author]["processed_projects"][-100:]

# ĐẨY LÊN SHEETS (BỌC THÉP CHỐNG TRÙNG LẶP)
def sync_to_sheet(db, sheet, all_values):
    data_rows = all_values[3:] if len(all_values) > 3 else []
    new_data_rows = []
    existing_usernames = set()
    
    for row in data_rows:
        if not row or not row[0].strip(): continue
        username = row[0].strip()
        existing_usernames.add(username)
        while len(row) < 7: row.append("")
        
        user_data = db.get(username)
        if user_data:
            row[1] = str(user_data["score"])
            row[2] = str(user_data.get("total_deducted", 0))
            row[4] = user_data.get("last_active_date", "")
            
            if user_data.get("new_logs"):
                added_log = "\n".join(user_data["new_logs"])
                row[5] = row[5].strip() + "\n" + added_log if row[5].strip() else added_log
                user_data["new_logs"] = []
            
            # XỬ LÝ CHỐNG TRÙNG LẶP BÌNH LUẬN TRƯỚC KHI NỐI VÀO SHEET
            if user_data.get("new_comments"):
                existing_sheet_comments = row[6].strip()
                valid_new_texts = []
                
                for cmt in user_data["new_comments"]:
                    # Chỉ lấy những ID chưa từng xuất hiện trong ô hiện tại
                    if cmt["id"] not in existing_sheet_comments:
                        valid_new_texts.append(cmt["text"])
                
                if valid_new_texts:
                    added_text = "\n".join(valid_new_texts)
                    row[6] = existing_sheet_comments + "\n" + added_text if existing_sheet_comments else added_text
                
                user_data["new_comments"] = [] 

        new_data_rows.append(row)
        
    for username, user_data in db.items():
        if username not in existing_usernames:
            added_text = "\n".join([cmt["text"] for cmt in user_data.get("new_comments", [])])
            added_log = "\n".join(user_data.get("new_logs", []))
            new_row = [
                username, str(user_data["score"]), str(user_data.get("total_deducted", 0)),
                "", user_data.get("last_active_date", ""), added_log, added_text
            ]
            user_data["new_comments"] = []
            user_data["new_logs"] = []
            new_data_rows.append(new_row)
            
    if new_data_rows:
        sheet.update(values=new_data_rows, range_name='A4', value_input_option='USER_ENTERED')
        print("Đồng bộ Sheets thành công!")

def main():
    db = load_db()
    sheet = None
    all_values = []

    try:
        sheet = get_google_sheet()
        if sheet: all_values = sync_from_sheet(db, sheet)
    except Exception as e: print(f"Lỗi đọc Google Sheets: {e}")

    for proj in fetch_projects(): process_project(proj, db)

    comments = fetch_comments()
    for comment in comments:
        process_comment(comment, db)
        if comment.get("reply_count", 0) > 0:
            time.sleep(0.5)
            for reply in fetch_replies(comment["id"]): process_comment(reply, db)

    if sheet:
        try: sync_to_sheet(db, sheet, all_values)
        except Exception as e: print(f"Lỗi ghi Google Sheets: {e}")

    save_db(db)
    print("Hoàn tất.")

if __name__ == "__main__":
    main()