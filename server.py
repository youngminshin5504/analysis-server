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
TEMPLATES_DB_FILE = os.path.join(DATA_DIR, "course_templates.json")
API_SECRET_KEY = os.getenv("API_KEY")
if not API_SECRET_KEY:
    raise ValueError("필수 환경 변수가 설정되지 않았습니다: API_KEY")
ADMIN_PASSWORD = "dusrntlf"
KST = pytz.timezone('Asia/Seoul')

def init_all_dbs():
    paths_to_create = [DATA_DIR, app.config["SESSION_FILE_DIR"]]
    for p in paths_to_create:
        if not os.path.exists(p): os.makedirs(p)
    for db_path in [DB_FILE, FORMS_DB_FILE, TEMPLATES_DB_FILE]:
        if not os.path.exists(db_path):
            with open(db_path, 'w', encoding='utf-8') as f: json.dump([], f, ensure_ascii=False, indent=2)

# --- 헬퍼 함수: 경로 생성 로직 수정 ---
def get_student_paths(subject, course_series, student_id):
    """학생의 과목/수업 시리즈별 데이터 경로를 생성하고 반환"""
    s_id_safe = student_id.replace('/', '_')
    series_dir = os.path.join(STUDENT_DB_DIRECTORY, subject, course_series)
    backup_dir = os.path.join(series_dir, "backups")
    main_profile_path = os.path.join(series_dir, f"{s_id_safe}.pkl")
    return series_dir, backup_dir, main_profile_path

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

# --- 수업 템플릿 및 수업 관리 API ---
@app.route('/api/course-templates', methods=['GET'])
def get_course_templates():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    try:
        with open(TEMPLATES_DB_FILE, 'r', encoding='utf-8') as f: templates = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): templates = []
    return jsonify(sorted(templates, key=lambda x: x['name']))

@app.route('/api/forms', methods=['GET'])
def get_forms():
    is_active_filter = request.args.get('active', 'false').lower() == 'true'
    status_filter = request.args.get('status', 'active') 
    all_forms = []
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: all_forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return jsonify([])
    if is_active_filter:
        today = datetime.now(KST).date()
        start_buffer_date = today + timedelta(days=7)
        active_forms = []
        for form in all_forms:
            if form.get('status', 'active') != 'active': continue
            try:
                start_date = datetime.strptime(form.get('startDate', '1970-01-01'), '%Y-%m-%d').date()
                end_date = datetime.strptime(form.get('endDate', '2999-12-31'), '%Y-%m-%d').date()
                if today <= end_date and start_date <= start_buffer_date: active_forms.append(form)
            except (ValueError, TypeError): continue
        return jsonify(active_forms)
    else:
        if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
        return jsonify([f for f in all_forms if f.get('status', 'active') == status_filter])

@app.route('/api/forms', methods=['POST'])
def add_form():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    data = request.get_json()
    new_form_data = data.get('form_data')
    
    # --- [버그 수정] ---
    # new_form_data가 없을 경우, 잘못된 요청으로 간주하고 400 오류를 반환하여 서버 다운 방지
    if not new_form_data:
        return jsonify({"error": "잘못된 수업 데이터 형식입니다."}), 400
    # --- [수정 완료] ---

    template_name = data.get('templateName', '').strip()

    if data.get('saveAsTemplate') and template_name:
        try:
            with open(TEMPLATES_DB_FILE, 'r', encoding='utf-8') as f: templates = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): templates = []
        template_data = { "id": f"template_{datetime.now().timestamp()}", "name": template_name, "subject": new_form_data.get('subject'), "startNumber": new_form_data.get('startNumber'), "endNumber": new_form_data.get('endNumber') }
        templates.append(template_data)
        with open(TEMPLATES_DB_FILE, 'w', encoding='utf-8') as f: json.dump(templates, f, ensure_ascii=False, indent=2)
    
    series_name_source = data.get('selectedTemplateName') or new_form_data.get('name', '').split('(')[0].strip()
    new_form_data['course_series'] = re.sub(r'[\s\/:*?"<>|]', '_', series_name_source)

    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): forms = []
    new_form_data['status'] = 'active'
    forms.append(new_form_data)
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f: json.dump(forms, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "새로운 수업이 성공적으로 개설되었습니다."}), 201

@app.route('/api/forms/<form_id>/status', methods=['PUT'])
def update_form_status(form_id):
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    new_status = request.json.get('status')
    if new_status not in ['active', 'archived']: return jsonify({"error": "잘못된 상태 값입니다."}), 400
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return jsonify({"error": "수업 데이터를 찾을 수 없습니다."}), 404
    form_found = False
    for form in forms:
        if form.get('id') == form_id: form['status'] = new_status; form_found = True; break
    if not form_found: return jsonify({"error": "해당 ID의 수업을 찾을 수 없습니다."}), 404
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f: json.dump(forms, f, ensure_ascii=False, indent=2)
    action = "폐강" if new_status == 'archived' else '복원'
    return jsonify({"message": f"수업이 성공적으로 {action} 처리되었습니다."})

# --- (이하 코드는 이전과 동일하므로 생략 없이 모두 포함) ---

# --- 데이터 제출 및 처리 API ---
@app.route('/submit', methods=['POST'])
def submit_data():
    data = request.get_json()
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
        target_form = next((form for form in forms if form['id'] == data.get('form_id')), None)
        if target_form:
            data['course_series'] = target_form.get('course_series', 'default')
        else:
            data['course_series'] = 'default'
    except:
        data['course_series'] = 'default'
    db_data = []
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): pass
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
    student_id = data.get('student_id'); subject = data.get('subject'); course_series = data.get('course_series')
    series_dir, backup_dir, main_profile_path = get_student_paths(subject, course_series, student_id)
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
    student_id = data.get('student_id'); subject = data.get('subject'); course_series = data.get('course_series'); final_profile = data.get('final_profile')
    _, _, main_profile_path = get_student_paths(subject, course_series, student_id)
    with open(main_profile_path, 'wb') as f: pickle.dump(final_profile, f)
    return jsonify({"message": f"'{student_id}' 학생({subject}/{course_series})의 프로필이 성공적으로 저장되었습니다."})

@app.route('/api/student-data', methods=['DELETE'])
def delete_student_data():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    student_id = request.json.get('student_id')
    if not student_id or not re.match(r"(.+?)\((\d{4})\)_(.+)", student_id):
        return jsonify({"error": "잘못된 학생 ID 형식입니다."}), 400
    s_name, s_phone, s_subj = re.match(r"(.+?)\((\d{4})\)_(.+)", student_id).groups()
    subject_dir = os.path.join(STUDENT_DB_DIRECTORY, s_subj)
    deleted_count = 0
    if os.path.exists(subject_dir):
        for series_dir_name in os.listdir(subject_dir):
            series_dir_path = os.path.join(subject_dir, series_dir_name)
            if not os.path.isdir(series_dir_path): continue
            
            student_profile_path_to_check = os.path.join(series_dir_path, f"{student_id.replace('/', '_')}.pkl")
            if os.path.exists(student_profile_path_to_check):
                shutil.rmtree(series_dir_path)
                deleted_count += 1
    if deleted_count > 0:
        return jsonify({"message": f"'{student_id}' 학생의 모든 수업 시리즈 데이터({deleted_count}개)가 영구적으로 삭제되었습니다."})
    else:
        return jsonify({"error": f"'{student_id}' 학생의 데이터를 찾을 수 없습니다."}), 404

# --- 재계산 API ---
@app.route('/api/recalculate-from-date', methods=['POST'])
def recalculate_from_date():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    data = request.json
    student_id = data.get('student_id'); start_date_str = data.get('start_date'); target_submission_id = data.get('submission_id')
    target_submission = None
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data_for_find = json.load(f)
        target_submission = next((item for item in db_data_for_find if item['id'] == target_submission_id), None)
    except:
        return jsonify({"error": "제출 기록을 찾는 데 실패했습니다."}), 404
    if not target_submission or 'course_series' not in target_submission:
        return jsonify({"error": "재계산에 필요한 수업 시리즈 정보를 찾을 수 없습니다."}), 400
    course_series = target_submission['course_series']
    s_name, s_phone, s_subj = (re.match(r"(.+?)\((\d{4})\)_(.+)", student_id) or (None, None, None)).groups()
    if not all([s_name, s_phone, s_subj]): return jsonify({"error": "잘못된 학생 ID 형식입니다."}), 400
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    _, backup_dir, main_profile_path = get_student_paths(s_subj, course_series, student_id)
    s_id_safe = student_id.replace('/', '_')
    backups = sorted(glob.glob(os.path.join(backup_dir, f"{s_id_safe}_*.pkl")), reverse=True)
    profile_to_restore = None; backup_to_keep = None
    for backup_file in backups:
        try:
            date_part = os.path.basename(backup_file).replace(f"{s_id_safe}_", "").replace(".pkl", "")
            if datetime.strptime(date_part, '%Y%m%d').date() < start_date:
                with open(backup_file, 'rb') as f: profile_to_restore = pickle.load(f)
                backup_to_keep = backup_file; break
        except (ValueError, IndexError): continue
    if profile_to_restore:
        with open(main_profile_path, 'wb') as f: pickle.dump(profile_to_restore, f)
    elif os.path.exists(main_profile_path): os.remove(main_profile_path)
    for backup_file in backups:
        if backup_file != backup_to_keep: os.remove(backup_file)
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except: db_data = []
    reprocess_count = 0
    for item in db_data:
        if (item.get('student_name') == s_name and item.get('phone_suffix') == s_phone and item.get('subject') == s_subj and item.get('course_series') == course_series):
            try:
                if datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).date() >= start_date:
                    item['status'] = 'pending'; item.pop('processed_at', None); reprocess_count += 1
            except: continue
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)
    return jsonify({"message": f"'{student_id}' 학생의 '{course_series}' 수업 시리즈 데이터가 {start_date_str}부터 재처리 대기 상태로 변경되었습니다. 총 {reprocess_count}개 기록이 재설정되었습니다."})

# --- 데이터 조회 및 기타 관리 API ---
@app.route('/api/calendar/events', methods=['GET'])
def get_calendar_events():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    start_str, end_str = request.args.get('start'), request.args.get('end'); events_to_show = defaultdict(set)
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: 
            forms_info = {form['id']: form.get('name', 'N/A') for form in json.load(f) if form.get('status', 'active') == 'active'}
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
        for item in db_data:
            try:
                if start_str <= datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).strftime('%Y-%m-%d') < end_str:
                    if item.get('form_id') in forms_info: events_to_show[datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).strftime('%Y-%m-%d')].add(item.get('form_id'))
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
    init_len = len(db_data)
    db_data_after_delete = [item for item in db_data if item.get('id') != submission_id]
    if len(db_data_after_delete) == init_len: return jsonify({"error": "기록을 찾을 수 없습니다."}), 404
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
        paths_to_backup = [DB_FILE, FORMS_DB_FILE, TEMPLATES_DB_FILE, STUDENT_DB_DIRECTORY]
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