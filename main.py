import requests
import json
import os
import time
import html
import re
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ================= NẠP TỪ CẤM TỪ FILE TXT =================
BANNED_WORDS = []
try:
    file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'censorship-badwr.txt')
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as file:
            BANNED_WORDS = [line.strip() for line in file if line.strip()]
        print(f"Đã nạp thành công {len(BANNED_WORDS)} từ cấm.")
    else:
        print("Cảnh báo: Không tìm thấy file censorship-badwr.txt. Danh sách từ cấm đang trống.")
except Exception as e:
    print(f"Lỗi đọc file từ cấm: {e}")
# ==========================================================

STUDIO_ID = "33509364"
API_BASE = f"https://api.scratch.mit.edu/studios/{STUDIO_ID}/comments"
PROJECTS_API = f"https://api.scratch.mit.edu/studios/{STUDIO_ID}/projects"
ACTIVITY_API = f"https://api.scratch.mit.edu/studios/{STUDIO_ID}/activity"
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

def update_tier(score):
    if score >= 90: return "XS"
    elif score >= 30: return "Tốt"
    else: return "Kém"

def init_user(username):
    return {
        "active_dates": [],     
        "last_comment_date": "",
        "total_deducted": 0,    
        "new_comments": [], 
        "new_logs": [], 
        "processed_comments": [],
        "processed_projects": [],
        "processed_activities": [],
        "projects_today": 0,
        "last_project_date": ""
    }

def fetch_api(url):
    try: return requests.get(f"{url}?offset=0&limit=40", timeout=10).json()
    except: return []

def fetch_replies(comment_id):
    try: return requests.get(f"{API_BASE}/{comment_id}/replies", timeout=10).json()
    except: return []

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
        while len(row) < 8: row.append("")
        
        if username not in db: db[username] = init_user(username)
        
        deducted_str = row[2].strip()
        db[username]["total_deducted"] = int(deducted_str) if deducted_str.isdigit() else 0
        
    return all_values

def penalize(author, points, log_msg, db):
    db[author]["total_deducted"] += points
    db[author].setdefault("new_logs", []).append(log_msg)
    db[author]["active_dates"] = [] 

def record_active_date(author, date_str, db):
    if not date_str: return
    user = db[author]
    
    if date_str not in user["active_dates"]:
        user["active_dates"].append(date_str)
        user["active_dates"].sort()
        
        if len(user["active_dates"]) >= 30:
            if user["total_deducted"] > 0:
                user["total_deducted"] = max(0, user["total_deducted"] - 10)
                user["new_logs"].append(f"[{date_str}] 🎉 +10đ (Đã trừ vào Tổng Điểm Phạt vì 30 ngày HĐ)")
            
            user["active_dates"] = [date_str] 
            
        if user["total_deducted"] == 0:
            user["active_dates"] = [user["active_dates"][-1]]

def process_activity(act, db):
    act_id = str(act.get("id", ""))
    author = act.get("actor_username")
    if not author: return
    date_str = act.get("datetime_created", "")[:10]
    
    if author not in db: db[author] = init_user(author)
    if act_id in db[author].get("processed_activities", []): return
    
    record_active_date(author, date_str, db)
    db[author].setdefault("processed_activities", []).append(act_id)
    db[author]["processed_activities"] = db[author]["processed_activities"][-100:]

def process_project(project, db):
    author = project.get("username", project.get("creator"))
    if not author: return
    author = str(author)
    proj_id = str(project["id"])
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    if author not in db: db[author] = init_user(author)
    if proj_id in db[author].get("processed_projects", []): return

    record_active_date(author, date_str, db)

    if db[author].get("last_project_date") != date_str:
        db[author]["last_project_date"] = date_str
        db[author]["projects_today"] = 0
        
    db[author]["projects_today"] += 1
    
    if db[author]["projects_today"] > 5:
        penalize(author, 5, f"[{date_str}] ⚠️ Quá 5 dự án/ngày (-5đ)", db)

    db[author].setdefault("processed_projects", []).append(proj_id)
    db[author]["processed_projects"] = db[author]["processed_projects"][-100:]

def process_comment(comment, db):
    comment_id = str(comment["id"])
    author = comment["author"]["username"]
    date_str = comment["datetime_created"][:10] 

    if author not in db: db[author] = init_user(author)
    
    db[author]["last_comment_date"] = date_str
    if comment_id in db[author].get("processed_comments", []): return

    record_active_date(author, date_str, db)
            
    raw_content = html.unescape(comment["content"])
    clean_content = re.sub(r'<[^>]+>', '', raw_content).strip()
    
    # KÍCH HOẠT QUÉT TỪ CẤM TỪ DANH SÁCH FILE TXT
    is_banned = False
    if BANNED_WORDS:
        is_banned = any(word.lower() in clean_content.lower() for word in BANNED_WORDS)
    tag = "[⚠️ TỪ CẤM] " if is_banned else ""
    
    formatted_comment = f"{tag}{comment_id} ({clean_content})"
    
    db[author].setdefault("new_comments", []).append({"id": comment_id, "text": formatted_comment})
    db[author].setdefault("processed_comments", []).append(comment_id)
    db[author]["processed_comments"] = db[author]["processed_comments"][-100:]

def sync_to_sheet(db, sheet, all_values):
    data_rows = all_values[3:] if len(all_values) > 3 else []
    new_data_rows = []
    existing_usernames = set()
    current_row_num = 4 
    
    for row in data_rows:
        if not row or not row[0].strip(): continue
        username = row[0].strip()
        existing_usernames.add(username)
        while len(row) < 8: row.append("")
        
        user_data = db.get(username)
        if user_data:
            row[1] = f"=100-C{current_row_num}"
            row[2] = str(user_data.get("total_deducted", 0))
            
            active_list = user_data.get("active_dates", [])
            row[4] = "\n".join(active_list) if active_list else ""
            if user_data.get("last_comment_date"): row[5] = user_data["last_comment_date"]
            
            if user_data.get("new_logs"):
                added_log = "\n".join(user_data["new_logs"])
                row[6] = row[6].strip() + "\n" + added_log if row[6].strip() else added_log
                user_data["new_logs"] = []
            
            if user_data.get("new_comments"):
                existing_sheet_comments = row[7].strip()
                valid_new_texts = [cmt["text"] for cmt in user_data["new_comments"] if cmt["id"] not in existing_sheet_comments]
                if valid_new_texts:
                    added_text = "\n".join(valid_new_texts)
                    row[7] = existing_sheet_comments + "\n" + added_text if existing_sheet_comments else added_text
                user_data["new_comments"] = [] 

        new_data_rows.append(row)
        current_row_num += 1
        
    for username, user_data in db.items():
        if username not in existing_usernames:
            added_text = "\n".join([cmt["text"] for cmt in user_data.get("new_comments", [])])
            added_log = "\n".join(user_data.get("new_logs", []))
            active_list = user_data.get("active_dates", [])
            
            new_row = [
                username, 
                f"=100-C{current_row_num}",
                str(user_data.get("total_deducted", 0)),
                "", 
                "\n".join(active_list) if active_list else "", 
                user_data.get("last_comment_date", ""), 
                added_log, 
                added_text
            ]
            user_data["new_comments"] = []
            user_data["new_logs"] = []
            new_data_rows.append(new_row)
            current_row_num += 1
            
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

    for act in fetch_api(ACTIVITY_API): process_activity(act, db)
    for proj in fetch_api(PROJECTS_API): process_project(proj, db)

    comments = fetch_api(API_BASE)
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