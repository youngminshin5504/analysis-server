# --- 필요한 라이브러리 불러오기 ---
from flask import Flask, request, jsonify, render_template, session, make_response, send_file
from flask_session import Session
import json
import os
import re
import glob
from datetime import datetime, timedelta
from collections import defaultdict
import pytz
import io
import zipfile
import shutil
import pickle

# --- Flask 앱 초기화 및 설정 ---
app = Flask(__name__, template_folder='.')
app.config["SECRET_KEY"] = os.getenv("SESSION_KEY", "a_super_secret_key_for_session_management_!@#$")
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "/var/data/sessions"
Session(app)

# --- 경로 및 상수 설정 ---
DATA_DIR = "/var/data"
STUDENT_DB_DIRECTORY = os.path.join(DATA_DIR, "students")
DB_FILE = os.path.join(DATA_DIR, "submissions.json")
FORMS_DB_FILE = os.path.join(DATA_DIR, "forms.json")
API_SECRET_KEY = os.getenv("API_KEY")
if not API_SECRET_KEY:
    raise ValueError("필수 환경 변수가 설정되지 않았습니다: API_KEY")
ADMIN_PASSWORD = "dusrntlf"
KST = pytz.timezone('Asia/Seoul')

def init_all_dbs():
    paths_to_create = [DATA_DIR, app.config["SESSION_FILE_DIR"]]
    for p in paths_to_create:
        if not os.path.exists(p): os.makedirs(p)
    for db_path in [DB_FILE, FORMS_DB_FILE]:
        if not os.path.exists(db_path):
            with open(db_path, 'w', encoding='utf-8') as f: json.dump([], f, ensure_ascii=False, indent=2)

# --- 헬퍼 함수 ---
def get_student_paths(subject_category, class_name, student_id):
    s_id_safe = student_id.replace('/', '_').replace('\\', '_')
    class_name_safe = class_name.replace('/', '_').replace('\\', '_')
    
    subject_dir = os.path.join(STUDENT_DB_DIRECTORY, subject_category)
    main_profile_path = os.path.join(subject_dir, f"{s_id_safe}.pkl")
    backup_dir = os.path.join(subject_dir, class_name_safe, "backups")
    
    return subject_dir, backup_dir, main_profile_path

# --- 인증 관련 API ---
def is_admin_session(): return session.get('is_admin', False)
def is_admin_apikey(): return request.headers.get('X-API-KEY') == API_SECRET_KEY

@app.route('/api/login', methods=['POST'])
def login():
    if request.json.get('password') == ADMIN_PASSWORD:
        session['is_admin'] = True; return jsonify({"message": "로그인 성공"})
    return jsonify({"error": "비밀번호가 틀렸습니다."}), 401
@app.route('/api/logout', methods=['POST'])
def logout(): session.pop('is_admin', None); return jsonify({"message": "로그아웃 성공"})
@app.route('/api/auth-status', methods=['GET'])
def auth_status(): return jsonify({"is_admin": is_admin_session()})

# --- 웹 페이지 서빙 ---
@app.route('/')
def index():
    resp = make_response(render_template('index.html'))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '-1'
    return resp

# --- 수업(Form) 관리 API ---
@app.route('/api/forms', methods=['GET'])
def get_forms():
    is_active_filter = request.args.get('active', 'false').lower() == 'true'
    all_forms = []
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: all_forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return jsonify([])

    if is_active_filter: # 조교용 API
        today = datetime.now(KST).date()
        start_buffer_date = today + timedelta(days=7)
        active_forms = []
        for form in all_forms:
            try:
                start_date = datetime.strptime(form.get('startDate', '1970-01-01'), '%Y-%m-%d').date()
                end_date = datetime.strptime(form.get('endDate', '2999-12-31'), '%Y-%m-%d').date()
                if today <= end_date and start_date <= start_buffer_date: active_forms.append(form)
            except (ValueError, TypeError): continue
        return jsonify(active_forms)
    else: # 관리자용 API
        if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
        
        grouped_forms = defaultdict(lambda: {'subject': '', 'instance_count': 0, 'latest_date': '1970-01-01'})
        for form in all_forms:
            name = form.get('name')
            if not name: continue
            group = grouped_forms[name]
            group['subject'] = form.get('subject')
            group['instance_count'] += 1
            if form.get('startDate') > group['latest_date']:
                group['latest_date'] = form.get('startDate')
        
        result = [{'name': name, 'subject': data['subject'], 'instance_count': data['instance_count'], 'latest_date': data['latest_date']} for name, data in grouped_forms.items()]
        result.sort(key=lambda x: x['latest_date'], reverse=True)
        return jsonify(result)

@app.route('/api/forms/by-name', methods=['GET'])
def get_forms_by_name():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    name = request.args.get('name')
    if not name: return jsonify({"error": "수업 이름이 필요합니다."}), 400
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: all_forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return jsonify([])
    
    instances = [form for form in all_forms if form.get('name') == name]
    instances.sort(key=lambda x: x.get('startDate'), reverse=True)
    return jsonify(instances)

@app.route('/api/forms', methods=['POST'])
def add_form():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    new_form_data = request.get_json()
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): forms = []
    forms.append(new_form_data)
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f: json.dump(forms, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "새로운 수업이 성공적으로 개설되었습니다."}), 201

@app.route('/api/forms/<form_id>', methods=['DELETE'])
def delete_form(form_id):
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return jsonify({"error": "파일을 찾을 수 없습니다."}), 404
    forms_after_delete = [f for f in forms if f.get('id') != form_id]
    if len(forms) == len(forms_after_delete): return jsonify({"error": "삭제할 수업을 찾을 수 없습니다."}), 404
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f: json.dump(forms_after_delete, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "수업이 성공적으로 삭제되었습니다."})

@app.route('/api/forms/by-name', methods=['DELETE'])
def delete_forms_by_name():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    name = request.json.get('name')
    if not name: return jsonify({"error": "수업 이름이 필요합니다."}), 400
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return jsonify({"error": "파일을 찾을 수 없습니다."}), 404
    forms_after_delete = [f for f in forms if f.get('name') != name]
    if len(forms) == len(forms_after_delete): return jsonify({"error": "삭제할 수업 그룹을 찾을 수 없습니다."}), 404
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f: json.dump(forms_after_delete, f, ensure_ascii=False, indent=2)
    return jsonify({"message": f"'{name}' 수업 그룹과 관련된 모든 날짜의 수업이 삭제되었습니다."})

# --- 데이터 제출 및 처리 API ---
@app.route('/submit', methods=['POST'])
def submit_data():
    data = request.get_json()
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): db_data = []

    form_id = data.get('form_id')
    class_name = "Unknown"
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
        for form in forms:
            if form.get('id') == form_id:
                class_name = form.get('name')
                break
    except: pass
    data['class_name'] = class_name
    
    now_kst = datetime.now(KST)
    today_kst_str = now_kst.strftime('%Y-%m-%d')
    key_to_check = (today_kst_str, data.get('student_name'), data.get('phone_suffix'), data.get('form_id'))
    found_and_updated = False
    for i, item in enumerate(db_data):
        try:
            item_date_str = datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).strftime('%Y-%m-%d')
            if (item_date_str, item.get('student_name'), item.get('phone_suffix'), item.get('form_id')) == key_to_check:
                data['id'] = item['id']; data['status'] = 'pending'; data['submitted_at'] = now_kst.isoformat()
                db_data[i] = data; found_and_updated = True; break
        except (ValueError, TypeError): continue
    if not found_and_updated:
        data['id'] = (db_data[-1]['id'] + 1) if db_data else 1; data['status'] = 'pending'; data['submitted_at'] = now_kst.isoformat(); db_data.append(data)
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "데이터가 성공적으로 제출되었습니다.", "id": data['id']}), 201

@app.route('/pending-data', methods=['GET'])
def get_pending_data():
    if not is_admin_apikey(): return jsonify({"error": "권한이 없습니다."}), 401
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except: db_data = []
    pending_list = [item for item in db_data if item.get('status') == 'pending']
    pending_list.sort(key=lambda x: x.get('submitted_at', ''))
    return jsonify(pending_list)

@app.route('/mark-processed', methods=['POST'])
def mark_processed():
    if not is_admin_apikey(): return jsonify({"error": "권한이 없습니다."}), 401
    processed_ids = request.get_json().get('ids', []);
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except: db_data = []
    now_kst_iso = datetime.now(KST).isoformat()
    for item in db_data:
        if item.get('id') in processed_ids: item['status'] = 'processed'; item['processed_at'] = now_kst_iso
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)
    return jsonify({"message": f"{len(processed_ids)}개 항목이 처리 완료로 표시되었습니다."})

# --- 학생 데이터(.pkl) 관리 API ---
@app.route('/api/student-profile/initial', methods=['POST'])
def get_initial_student_profile():
    if not is_admin_apikey(): return jsonify({"error": "권한이 없습니다."}), 401
    data = request.json
    student_id = data.get('student_id')
    subject_category = data.get('subject')
    class_name = data.get('class_name')
    
    subject_dir, backup_dir, main_profile_path = get_student_paths(subject_category, class_name, student_id)
    os.makedirs(subject_dir, exist_ok=True)
    os.makedirs(backup_dir, exist_ok=True)
    
    today_str = datetime.now(KST).strftime('%Y%m%d')
    backup_path = os.path.join(backup_dir, f"{student_id.replace('/', '_')}_{today_str}.pkl")
    profile = {comp: 50.0 for comp in ('통찰력', '계산력', '논리력', '융합력', '개념', '전략')}
    if os.path.exists(backup_path):
        with open(backup_path, 'rb') as f: profile = pickle.load(f)
    else:
        if os.path.exists(main_profile_path):
            with open(main_profile_path, 'rb') as f: profile = pickle.load(f)
        with open(backup_path, 'wb') as f: pickle.dump(profile, f)
    return jsonify({"profile": profile})

@app.route('/api/student-profile/commit', methods=['POST'])
def commit_student_profile():
    if not is_admin_apikey(): return jsonify({"error": "권한이 없습니다."}), 401
    data = request.json
    student_id = data.get('student_id')
    subject_category = data.get('subject')
    class_name = data.get('class_name')
    final_profile = data.get('final_profile')
    _, _, main_profile_path = get_student_paths(subject_category, class_name, student_id)
    with open(main_profile_path, 'wb') as f: pickle.dump(final_profile, f)
    return jsonify({"message": f"'{student_id}' 학생({subject_category})의 프로필이 성공적으로 저장되었습니다."})

@app.route('/api/student-data', methods=['DELETE'])
def delete_student_data():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    student_id = request.json.get('student_id')
    if not student_id or not re.match(r"(.+?)\((\d{4})\)_(.+)", student_id):
        return jsonify({"error": "잘못된 학생 ID 형식입니다."}), 400
    s_name, s_phone, s_subj_category = re.match(r"(.+?)\((\d{4})\)_(.+)", student_id).groups()
    
    subject_dir = os.path.join(STUDENT_DB_DIRECTORY, s_subj_category)
    if not os.path.exists(subject_dir):
        return jsonify({"error": f"'{student_id}' 학생의 데이터를 찾을 수 없습니다."}), 404

    main_profile_path = os.path.join(subject_dir, f"{student_id.replace('/', '_')}.pkl")
    if os.path.exists(main_profile_path):
        os.remove(main_profile_path)

    for class_folder in os.listdir(subject_dir):
        backup_dir = os.path.join(subject_dir, class_folder, "backups")
        if os.path.isdir(backup_dir):
            for backup_file in glob.glob(os.path.join(backup_dir, f"{student_id.replace('/', '_')}_*.pkl")):
                os.remove(backup_file)
                
    return jsonify({"message": f"'{student_id}' 학생의 모든 프로필과 백업 데이터가 영구적으로 삭제되었습니다."})

# --- 재계산 API ---
@app.route('/api/recalculate-from-date', methods=['POST'])
def recalculate_from_date():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    data = request.json
    student_id = data.get('student_id')
    start_date_str = data.get('start_date')
    s_name, s_phone, s_subj_category = (re.match(r"(.+?)\((\d{4})\)_(.+)", student_id) or (None, None, None)).groups()
    if not all([s_name, s_phone, s_subj_category]): return jsonify({"error": "잘못된 학생 ID 형식입니다."}), 400
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()

    subject_dir = os.path.join(STUDENT_DB_DIRECTORY, s_subj_category)
    main_profile_path = os.path.join(subject_dir, f"{student_id.replace('/', '_')}.pkl")
    
    all_backups = []
    if os.path.exists(subject_dir):
        for root, dirs, files in os.walk(subject_dir):
            for file in files:
                if file.startswith(student_id.replace('/', '_')) and file.endswith('.pkl') and "backups" in root:
                    all_backups.append(os.path.join(root, file))
    
    all_backups.sort(reverse=True)

    profile_to_restore = None; backup_to_keep = None
    for backup_file in all_backups:
        try:
            date_part = os.path.basename(backup_file).split('_')[-1].replace(".pkl", "")
            if datetime.strptime(date_part, '%Y%m%d').date() < start_date:
                with open(backup_file, 'rb') as f: profile_to_restore = pickle.load(f)
                backup_to_keep = backup_file; break
        except (ValueError, IndexError): continue

    if profile_to_restore:
        with open(main_profile_path, 'wb') as f: pickle.dump(profile_to_restore, f)
    elif os.path.exists(main_profile_path): os.remove(main_profile_path)
    
    for backup_file in all_backups:
        if backup_file != backup_to_keep: os.remove(backup_file)
        
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except: db_data = []
    reprocess_count = 0
    for item in db_data:
        if (item.get('student_name') == s_name and item.get('phone_suffix') == s_phone and item.get('subject') == s_subj_category):
            try:
                if datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).date() >= start_date:
                    item['status'] = 'pending'; item.pop('processed_at', None); reprocess_count += 1
            except: continue
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)
    return jsonify({"message": f"'{student_id}' 학생의 {start_date_str}부터의 모든 데이터가 재처리 대기 상태로 변경되었습니다. 총 {reprocess_count}개 기록이 재설정되었습니다."})

# --- 데이터 조회 및 기타 관리 API ---
@app.route('/api/calendar/events', methods=['GET'])
def get_calendar_events():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    start_str, end_str = request.args.get('start'), request.args.get('end'); events_to_show = defaultdict(set)
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: 
            forms_info = {form['id']: form.get('name', 'N/A') for form in json.load(f)}
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
        for item in db_data:
            try:
                item_date_str = datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).strftime('%Y-%m-%d')
                if start_str <= item_date_str < end_str and item.get('form_id') in forms_info:
                    events_to_show[item_date_str].add(item.get('form_id'))
            except: continue
    except: pass
    calendar_events = [{"title": forms_info.get(f_id, "알 수 없는 수업"), "start": d_str, "extendedProps": {"formId": f_id}} for d_str, f_ids in events_to_show.items() for f_id in f_ids]
    return jsonify(calendar_events)

@app.route('/api/data/by-date-form/<string:date_str>/<string:form_id>', methods=['GET'])
def get_data_by_date_and_form(date_str, form_id):
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    latest_submissions = {}
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
        for item in db_data:
            try:
                if datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).strftime('%Y-%m-%d') == date_str and item.get('form_id') == form_id:
                    s_key = (item.get('student_name'), item.get('phone_suffix'))
                    if s_key not in latest_submissions or item.get('submitted_at') > latest_submissions[s_key].get('submitted_at'):
                        item['student_id'] = f"{item.get('student_name')}({item.get('phone_suffix')})_{item.get('subject')}"
                        latest_submissions[s_key] = item
            except: continue
    except: pass
    return jsonify(list(latest_submissions.values()))

@app.route('/api/submission/<int:submission_id>', methods=['DELETE'])
def delete_submission(submission_id):
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except: return jsonify({"error": "파일을 찾을 수 없습니다."}), 404
    db_data_after_delete = [item for item in db_data if item.get('id') != submission_id]
    if len(db_data_after_delete) == len(db_data): return jsonify({"error": "기록을 찾을 수 없습니다."}), 404
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data_after_delete, f, ensure_ascii=False, indent=2)
    return jsonify({"message": f"ID {submission_id}번 기록이 삭제되었습니다."})

@app.route('/api/students', methods=['GET'])
def get_all_students():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    students = set()
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
        for item in db_data:
            if all(k in item for k in ['student_name', 'phone_suffix', 'subject']):
                students.add(f"{item['student_name']}({item['phone_suffix']})_{item['subject']}")
    except: pass
    return jsonify(sorted(list(students)))

@app.route('/api/backup/download', methods=['GET'])
def download_full_backup():
    if not is_admin_session(): return "권한이 없습니다.", 401
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        paths_to_backup = [DB_FILE, FORMS_DB_FILE, STUDENT_DB_DIRECTORY]
        for path in paths_to_backup:
            if not os.path.exists(path): continue
            if os.path.isfile(path):
                zf.write(path, os.path.basename(path))
            elif os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        archive_name = os.path.relpath(file_path, DATA_DIR)
                        zf.write(file_path, archive_name)
    memory_file.seek(0)
    backup_filename = f"backup_{datetime.now(KST).strftime('%Y-%m-%d_%H%M')}.zip"
    return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name=backup_filename)

if __name__ == '__main__':
    init_all_dbs()
    app.run(host='0.0.0.0', port=5000, debug=False)