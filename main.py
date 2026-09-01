import requests
import json
import os
import time
import html
import re
import traceback
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# ================= NẠP TỪ CẤM TỪ FILE TXT =================
BANNED_WORDS = []
try:
    file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'censorship-badwr.txt')
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as file:
            BANNED_WORDS = [word for word in file.read().splitlines() if word.strip()]
        print(f"Đã nạp thành công {len(BANNED_WORDS)} từ cấm.")
    else:
        print("Cảnh báo: Không tìm thấy file censorship-badwr.txt. Danh sách từ cấm đang trống.")
except Exception as e:
    print(f"Lỗi đọc file từ cấm: {e}")
# ==========================================================

STUDIO_ID = "33509364"
API_BASE = f"https://api.scratch.mit.edu/studios/{STUDIO_ID}/comments?limit=40&offset=0"
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
    try: 
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        return res.json()
    except Exception as e: 
        print(f"Lỗi lấy API ({url}): {e}")
        return []

def fetch_replies(comment_id, reply_count):
    replies = []
    for offset in range(0, reply_count + 40, 40):
        url = f"https://api.scratch.mit.edu/studios/{STUDIO_ID}/comments/{comment_id}/replies?limit=40&offset={offset}"
        try: 
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            data = res.json()
            if not data: break
            replies.extend(data)
            time.sleep(0.2)
        except Exception as e: 
            print(f"Lỗi lấy reply cho cmt {comment_id}: {e}")
            break
    return replies

def get_google_sheets():
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    sheet_url = os.environ.get('SHEET_URL')
    if not creds_json or not sheet_url: 
        print("Lỗi: Không tìm thấy Biến môi trường GOOGLE_CREDENTIALS hoặc SHEET_URL")
        return None, None
        
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url(sheet_url)
    
    # 1. Kết nối Tab Quản lý điểm (Cũ)
    main_sheet = spreadsheet.get_worksheet_by_id(1060874817)
    
    # 2. Kết nối Tab Mô phỏng archive (Mới)
    try:
        sim_sheet = spreadsheet.get_worksheet_by_id(1169567819)
    except Exception as e:
        print(f"Cảnh báo: Không thể mở tab Mô phỏng bằng ID 1169567819: {repr(e)}")
        sim_sheet = None
        
    return main_sheet, sim_sheet

def check_and_create_month_column(sheet):
    try:
        row3 = sheet.row_values(3)
        header_e = row3[4] if len(row3) > 4 else ""
        
        local_dt = datetime.utcnow() + timedelta(hours=7)
        current_month_label = f"Bình luận {local_dt.month}/{local_dt.year}"
        
        if header_e == "Bình luận" or not header_e:
            sheet.update_acell('E3', current_month_label)
            print(f"Đã cập nhật tiêu đề cột E thành: {current_month_label}")
            
        elif header_e != current_month_label and header_e.startswith("Bình luận"):
            print(f"Phát hiện tháng mới! Đang tạo cột {current_month_label}...")
            
            body = {
                "requests": [{
                    "insertDimension": {
                        "range": {
                            "sheetId": sheet.id,
                            "dimension": "COLUMNS",
                            "startIndex": 4, 
                            "endIndex": 5
                        },
                        "inheritFromBefore": False 
                    }
                }]
            }
            sheet.spreadsheet.batch_update(body)
            sheet.update_acell('E3', current_month_label)
            print("Đã tạo cột tháng mới thành công!")
            time.sleep(2) 
            
    except Exception as e:
        print(f"Lỗi khi kiểm tra/tạo cột tháng mới: {e}")

def sync_from_sheet(db, all_values):
    data_rows = all_values[4:] if len(all_values) > 4 else []
    for row in data_rows:
        if not row or not row[0].strip(): continue
        username = row[0].strip()
        if username not in db: db[username] = init_user(username)

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
    
    if db[author]["projects_today"] == 6:
        penalize(author, 5, f"[{date_str}] ⚠️ Quá 5 dự án/ngày (-5đ)", db)

    db[author].setdefault("processed_projects", []).append(proj_id)
    db[author]["processed_projects"] = db[author]["processed_projects"][-100:]

def process_comment(comment, db):
    comment_id = str(comment["id"])
    author = comment["author"]["username"]
    
    raw_dt = comment.get("datetime_created", "")
    date_str = raw_dt[:10] 

    if author not in db: db[author] = init_user(author)
    
    db[author]["last_comment_date"] = date_str
    if comment_id in db[author].get("processed_comments", []): return

    record_active_date(author, date_str, db)
            
    raw_content = html.unescape(comment.get("content", ""))
    clean_content = re.sub(r'<[^>]+>', '', raw_content).strip()
    
    is_banned = False
    if BANNED_WORDS:
        text_lower = clean_content.lower()
        for word in BANNED_WORDS:
            if re.search(rf'\b{re.escape(word.lower())}\b', text_lower):
                is_banned = True
                break

    try:
        utc_dt = datetime.strptime(raw_dt, "%Y-%m-%dT%H:%M:%S.%fZ")
        local_dt = utc_dt + timedelta(hours=7)
        time_display = local_dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        time_display = raw_dt[:10]

    tag = "[⚠️ TỪ CẤM] " if is_banned else ""
    formatted_comment = f"[{time_display}] {tag}{comment_id} ({clean_content})"
    
    db[author].setdefault("new_comments", []).append({"id": comment_id, "text": formatted_comment})
    db[author].setdefault("processed_comments", []).append(comment_id)
    db[author]["processed_comments"] = db[author]["processed_comments"][-250:]

# ================= HÀM XỬ LÝ VÀ CHUẨN BỊ MÔ PHỎNG =================
def format_time(raw_dt):
    try:
        utc_dt = datetime.strptime(raw_dt, "%Y-%m-%dT%H:%M:%S.%fZ")
        local_dt = utc_dt + timedelta(hours=7)
        return local_dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return raw_dt[:10]

def clean_text(raw_content):
    raw_content = html.unescape(raw_content)
    return re.sub(r'<[^>]+>', '', raw_content).strip()

def sync_simulation_sheet(db, sim_sheet):
    if not sim_sheet or "SYSTEM_THREADS_STORAGE" not in db: return
    
    threads = db["SYSTEM_THREADS_STORAGE"]
    
    sorted_threads = sorted(threads.values(), key=lambda x: x.get("datetime_created", ""), reverse=True)
    rows = []
    
    for thread in sorted_threads:
        main_dt = thread.get("datetime_created", "")
        main_time = format_time(main_dt)
        main_content = clean_text(thread.get("content", ""))
        
        main_text = f"({thread.get('id', '')} - {thread.get('author', '')} - {main_time}) {main_content}"
        rows.append([main_text, ""])
        
        replies = thread.get("replies", {})
        sorted_replies = sorted(replies.values(), key=lambda x: x.get("datetime_created", ""))
        
        for reply in sorted_replies:
            reply_dt = reply.get("datetime_created", "")
            reply_time = format_time(reply_dt)
            reply_content = clean_text(reply.get("content", ""))
            
            reply_text = f"({reply.get('id', '')} - {reply.get('author', '')} - {reply_time}) {reply_content}"
            rows.append(["", reply_text])

    if not rows:
        rows = [["", ""]]

    try:
        sim_sheet.resize(rows=len(rows), cols=2)
    except Exception as e:
        print(f"Lỗi khi resize Sheet Mô phỏng: {e}")
            
    try:
        sim_sheet.clear() 
    except Exception:
        pass
        
    try:
        sim_sheet.update(range_name='A1', values=rows, value_input_option='USER_ENTERED')
        print(f"Đã đồng bộ vĩnh viễn {len(rows)} dòng Archive vào Sheet 'Mô phỏng'!")
    except TypeError:
        sim_sheet.update('A1', rows, value_input_option='USER_ENTERED')
        print(f"Đã đồng bộ vĩnh viễn {len(rows)} dòng Archive vào Sheet 'Mô phỏng'!")
# ===================================================================

def sync_to_sheet(db, sheet, all_values):
    data_rows = all_values[4:] if len(all_values) > 4 else []
    new_data_rows = []
    existing_usernames = set()
    users_to_clear = [] 
    
    for row in data_rows:
        if not row or not row[0].strip(): continue
        username = row[0].strip()
        existing_usernames.add(username)
        
        while len(row) < 5: row.append("")
        
        user_data = db.get(username)
        if user_data:
            active_list = user_data.get("active_dates", [])
            if active_list: row[1] = "\n".join(active_list)
            
            if user_data.get("last_comment_date"): 
                row[2] = user_data["last_comment_date"]
            
            if user_data.get("new_logs"):
                added_log = "\n".join(user_data["new_logs"])
                row[3] = row[3].strip() + "\n" + added_log if row[3].strip() else added_log
            
            if user_data.get("new_comments"):
                existing_sheet_comments = row[4].strip()
                valid_new_texts = [cmt["text"] for cmt in user_data["new_comments"] if cmt["id"] not in existing_sheet_comments]
                if valid_new_texts:
                    added_text = "\n".join(valid_new_texts)
                    row[4] = existing_sheet_comments + "\n" + added_text if existing_sheet_comments else added_text
            
            users_to_clear.append(username)

        new_data_rows.append(row[:5])
        
    for username, user_data in db.items():
        if username not in existing_usernames and username != "SYSTEM_THREADS_STORAGE":
            added_text = "\n".join([cmt["text"] for cmt in user_data.get("new_comments", [])])
            added_log = "\n".join(user_data.get("new_logs", []))
            active_list = user_data.get("active_dates", [])
            
            new_row = [
                username,                                       
                "\n".join(active_list) if active_list else "",  
                user_data.get("last_comment_date", ""),         
                added_log,                                      
                added_text                                      
            ]
            new_data_rows.append(new_row)
            users_to_clear.append(username)
            
    if new_data_rows:
        try:
            sheet.update(range_name='A5', values=new_data_rows, value_input_option='USER_ENTERED')
            print("Đồng bộ Sheet Quản Lý (Cũ) thành công!")
        except TypeError:
            sheet.update('A5', new_data_rows, value_input_option='USER_ENTERED')
            print("Đồng bộ Sheet Quản Lý (Cũ) thành công!")
            
        for username in users_to_clear:
            if username in db:
                db[username]["new_comments"] = []
                db[username]["new_logs"] = []

def main():
    db = load_db()
    main_sheet = None
    sim_sheet = None
    all_values = []
    
    if "threads" in db:
        db["SYSTEM_THREADS_STORAGE"] = db.pop("threads")

    if "SYSTEM_THREADS_STORAGE" not in db:
        db["SYSTEM_THREADS_STORAGE"] = {}

    # TRÁNH SẬP GOOGLE SHEETS
    try:
        main_sheet, sim_sheet = get_google_sheets()
        if not main_sheet:
            print("Lỗi: Không thể kết nối Google Sheets (Tab Chính). Hủy chạy để bảo vệ dữ liệu.")
            return
            
        check_and_create_month_column(main_sheet)
        
        # --- CƠ CHẾ AUTO-RETRY CHỐNG SPAM API ---
        for attempt in range(3):
            try:
                all_values = main_sheet.get_all_values()
                break
            except Exception as read_err:
                if attempt < 2:
                    print(f"Bị chặn tạm thời bởi Google (Thử lại sau 5s)...")
                    time.sleep(5)
                else:
                    raise read_err
        # ----------------------------------------
                    
        if len(all_values) < 4:
            print("Lỗi: Dữ liệu Sheet trả về trống hoặc lỗi mạng. Hủy chạy để KHÔNG GHI ĐÈ nhầm.")
            return
            
        sync_from_sheet(db, all_values)
        
    except Exception as e: 
        print(f"\n================ LỖI KẾT NỐI ================")
        print(f"Lỗi đọc Google Sheets: {repr(e)}")
        traceback.print_exc() # Hàm này sẽ in ra chính xác lỗi nằm ở đâu
        print("=============================================\n")
        return 

    for act in fetch_api(f"{ACTIVITY_API}?limit=40&offset=0"): process_activity(act, db)
    for proj in fetch_api(f"{PROJECTS_API}?limit=40&offset=0"): process_project(proj, db)

    comments = []
    for offset in [0, 40, 80, 120, 160]:
        url = API_BASE.replace("offset=0", f"offset={offset}")
        data = fetch_api(url)
        if not data: break
        comments.extend(data)
        
    print(f"Đã tải {len(comments)} bình luận gốc.")

    for comment in comments:
        process_comment(comment, db)
        
        comment_id = str(comment["id"])
        if comment_id not in db["SYSTEM_THREADS_STORAGE"]:
            db["SYSTEM_THREADS_STORAGE"][comment_id] = {
                "id": comment_id,
                "author": comment["author"]["username"],
                "content": comment.get("content", ""),
                "datetime_created": comment.get("datetime_created", ""),
                "replies": {}
            }
        else:
            db["SYSTEM_THREADS_STORAGE"][comment_id]["content"] = comment.get("content", "")
            db["SYSTEM_THREADS_STORAGE"][comment_id]["datetime_created"] = comment.get("datetime_created", "")
            
        reply_count = comment.get("reply_count", 0)
        
        if reply_count > 0:
            replies_data = fetch_replies(comment["id"], reply_count)
            for reply in replies_data: 
                process_comment(reply, db)
                
                reply_id = str(reply["id"])
                db["SYSTEM_THREADS_STORAGE"][comment_id]["replies"][reply_id] = {
                    "id": reply_id,
                    "author": reply["author"]["username"],
                    "content": reply.get("content", ""),
                    "datetime_created": reply.get("datetime_created", "")
                }

    if main_sheet:
        try: sync_to_sheet(db, main_sheet, all_values)
        except Exception as e: print(f"Lỗi ghi Google Sheets (Tab Chính): {e}")
        
    if sim_sheet:
        sync_simulation_sheet(db, sim_sheet)

    save_db(db)
    print("Hoàn tất mọi tác vụ.")

if __name__ == "__main__":
    main()
