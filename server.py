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
import shutil # [신규] 디렉토리 삭제를 위해 추가
import pickle # [신규] 학생 프로필(pkl) 관리를 위해 추가

# --- Flask 앱 초기화 및 설정 ---
app = Flask(__name__, template_folder='.')
app.config["SECRET_KEY"] = os.getenv("SESSION_KEY", "a_super_secret_key_for_session_management_!@#$")
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "/var/data/sessions"
Session(app)

# --- 경로 및 상수 설정 ---
DATA_DIR = "/var/data"
STUDENT_DB_DIRECTORY = os.path.join(DATA_DIR, "students") # [변경] 기본 학생 데이터 경로
DB_FILE = os.path.join(DATA_DIR, "submissions.json")
FORMS_DB_FILE = os.path.join(DATA_DIR, "forms.json")
TEMPLATES_DB_FILE = os.path.join(DATA_DIR, "course_templates.json") # [신규] 수업 템플릿 DB 경로
API_SECRET_KEY = os.getenv("API_KEY")
if not API_SECRET_KEY:
    raise ValueError("필수 환경 변수가 설정되지 않았습니다: API_KEY")
ADMIN_PASSWORD = "dusrntlf"
KST = pytz.timezone('Asia/Seoul')

def init_all_dbs():
    # [변경] 관리할 경로에 STUDENT_DB_DIRECTORY 추가 (하위 폴더는 동적으로 생성)
    paths_to_create = [DATA_DIR, app.config["SESSION_FILE_DIR"]]
    for p in paths_to_create:
        if not os.path.exists(p): os.makedirs(p)
    # [변경] TEMPLATES_DB_FILE도 초기화 대상에 추가
    for db_path in [DB_FILE, FORMS_DB_FILE, TEMPLATES_DB_FILE]:
        if not os.path.exists(db_path):
            with open(db_path, 'w', encoding='utf-8') as f: json.dump([], f, ensure_ascii=False, indent=2)

# --- 인증 관련 API 및 함수 ---
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

# --- API 엔드포인트 ---
@app.route('/')
def index():
    resp = make_response(render_template('index.html'))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '-1'
    return resp

# --- [신규] 수업 템플릿 관리 API ---
@app.route('/api/course-templates', methods=['GET'])
def get_course_templates():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    try:
        with open(TEMPLATES_DB_FILE, 'r', encoding='utf-8') as f: templates = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): templates = []
    return jsonify(sorted(templates, key=lambda x: x['name']))

@app.route('/api/course-templates', methods=['POST'])
def add_course_template():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    new_template_data = request.get_json()
    try:
        with open(TEMPLATES_DB_FILE, 'r', encoding='utf-8') as f: templates = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): templates = []
    new_template_data['id'] = f"template_{datetime.now().timestamp()}"
    templates.append(new_template_data)
    with open(TEMPLATES_DB_FILE, 'w', encoding='utf-8') as f: json.dump(templates, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "새로운 수업 템플릿이 성공적으로 저장되었습니다.", "template": new_template_data}), 201

@app.route('/api/course-templates/<template_id>', methods=['DELETE'])
def delete_course_template(template_id):
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    templates = []
    try:
        with open(TEMPLATES_DB_FILE, 'r', encoding='utf-8') as f: templates = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): pass
    templates_after_delete = [t for t in templates if t.get('id') != template_id]
    if len(templates) == len(templates_after_delete): return jsonify({"error": "해당 ID의 템플릿을 찾을 수 없습니다."}), 404
    with open(TEMPLATES_DB_FILE, 'w', encoding='utf-8') as f: json.dump(templates_after_delete, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "수업 템플릿이 성공적으로 삭제되었습니다."})
# --- 여기까지 신규 기능 ---


# --- [변경] 수업(Form) 관리 API ---
@app.route('/api/forms', methods=['GET'])
def get_forms():
    # [변경] active 필터 외에 status 필터(active, archived) 추가
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
            # [변경] 상태가 'active'인 것만 필터링
            if form.get('status', 'active') != 'active': continue
            try:
                start_date = datetime.strptime(form.get('startDate', '1970-01-01'), '%Y-%m-%d').date()
                end_date = datetime.strptime(form.get('endDate', '2999-12-31'), '%Y-%m-%d').date()
                if today <= end_date and start_date <= start_buffer_date:
                    active_forms.append(form)
            except (ValueError, TypeError): continue
        return jsonify(active_forms)
    else:
        if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
        # [변경] 관리자 조회 시 status_filter 적용
        return jsonify([f for f in all_forms if f.get('status', 'active') == status_filter])

@app.route('/api/forms', methods=['POST'])
def add_form():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    new_form_data = request.get_json()
    forms = []
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): pass
    
    # [신규] status 필드를 'active'로 기본 설정
    new_form_data['status'] = 'active'
    
    forms.append(new_form_data)
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f: json.dump(forms, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "새로운 수업이 성공적으로 개설되었습니다."}), 201

# [신규] 수업 상태 변경(폐강/복원) API
@app.route('/api/forms/<form_id>/status', methods=['PUT'])
def update_form_status(form_id):
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    new_status = request.json.get('status')
    if new_status not in ['active', 'archived']:
        return jsonify({"error": "잘못된 상태 값입니다."}), 400
    
    forms = []
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({"error": "수업 데이터를 찾을 수 없습니다."}), 404
        
    form_found = False
    for form in forms:
        if form.get('id') == form_id:
            form['status'] = new_status
            form_found = True
            break
            
    if not form_found:
        return jsonify({"error": "해당 ID의 수업을 찾을 수 없습니다."}), 404
        
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f: json.dump(forms, f, ensure_ascii=False, indent=2)
    action = "폐강" if new_status == 'archived' else '복원'
    return jsonify({"message": f"수업이 성공적으로 {action} 처리되었습니다."})

@app.route('/api/forms/<form_id>', methods=['DELETE'])
def delete_form(form_id):
    # 이 함수는 이제 사용되지 않을 수 있으나, 만약을 위해 유지 (DB 완전 삭제용)
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    forms = []
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): pass
    forms_after_delete = [form for form in forms if form.get('id') != form_id]
    if len(forms) == len(forms_after_delete): return jsonify({"error": "해당 ID의 수업을 찾을 수 없습니다."}), 404
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f: json.dump(forms_after_delete, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "수업이 성공적으로 영구 삭제되었습니다."})


# --- 데이터 제출 및 처리 API (기존과 거의 동일) ---
@app.route('/submit', methods=['POST'])
def submit_data():
    data = request.get_json(); db_data = []
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): pass
    now_kst = datetime.now(KST); today_kst_str = now_kst.strftime('%Y-%m-%d')
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
    # [신규] hexstat.py가 시간 순서대로 처리할 수 있도록 제출 시간 기준으로 정렬하여 반환
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


# --- [신규] 학생 데이터(.pkl) 관리 API for hexstat.py ---
def get_student_paths(subject, student_id):
    """학생의 과목별 데이터 경로를 생성하고 반환하는 헬퍼 함수"""
    s_id_safe = student_id.replace('/', '_')
    subject_dir = os.path.join(STUDENT_DB_DIRECTORY, subject)
    backup_dir = os.path.join(subject_dir, "backups")
    main_profile_path = os.path.join(subject_dir, f"{s_id_safe}.pkl")
    return subject_dir, backup_dir, main_profile_path

@app.route('/api/student-profile/initial', methods=['POST'])
def get_initial_student_profile():
    """hexstat.py가 분석 시작 시 호출. 오늘자 백업을 생성/반환."""
    if not is_admin_apikey(): return jsonify({"error": "권한이 없습니다."}), 401
    data = request.json
    student_id = data.get('student_id')
    subject = data.get('subject')
    
    subject_dir, backup_dir, main_profile_path = get_student_paths(subject, student_id)
    os.makedirs(backup_dir, exist_ok=True)
    
    today_str = datetime.now(KST).strftime('%Y%m%d')
    backup_path = os.path.join(backup_dir, f"{student_id.replace('/', '_')}_{today_str}.pkl")

    profile = {comp: 50.0 for comp in ('통찰력', '계산력', '논리력', '융합력', '개념', '전략')} # 기본 프로필
    
    if os.path.exists(backup_path):
        with open(backup_path, 'rb') as f: profile = pickle.load(f)
    else:
        if os.path.exists(main_profile_path):
            with open(main_profile_path, 'rb') as f: profile = pickle.load(f)
        with open(backup_path, 'wb') as f: pickle.dump(profile, f)

    return jsonify({"profile": profile})

@app.route('/api/student-profile/commit', methods=['POST'])
def commit_student_profile():
    """hexstat.py가 분석 완료 후 호출. 최종 프로필을 저장."""
    if not is_admin_apikey(): return jsonify({"error": "권한이 없습니다."}), 401
    data = request.json
    student_id = data.get('student_id')
    subject = data.get('subject')
    final_profile = data.get('final_profile')

    _, _, main_profile_path = get_student_paths(subject, student_id)
    with open(main_profile_path, 'wb') as f: pickle.dump(final_profile, f)
    
    return jsonify({"message": f"'{student_id}' 학생({subject})의 프로필이 성공적으로 저장되었습니다."})


# --- [신규] 과거 데이터 재계산 요청 API ---
@app.route('/api/recalculate-from-date', methods=['POST'])
def recalculate_from_date():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    data = request.json
    student_id = data.get('student_id') # 형식: "학생이름(1234)_과목"
    start_date_str = data.get('start_date') # 형식: "YYYY-MM-DD"

    s_name, s_phone, s_subj = (re.match(r"(.+?)\((\d{4})\)_(.+)", student_id) or (None, None, None)).groups()
    if not all([s_name, s_phone, s_subj]):
        return jsonify({"error": "잘못된 학생 ID 형식입니다."}), 400

    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()

    # 1. 해당 날짜 이전의 가장 최신 백업 찾기
    subject_dir, backup_dir, main_profile_path = get_student_paths(s_subj, student_id)
    s_id_safe = student_id.replace('/', '_')
    
    backups = sorted(glob.glob(os.path.join(backup_dir, f"{s_id_safe}_*.pkl")), reverse=True)
    
    profile_to_restore = None
    backup_to_keep = None
    for backup_file in backups:
        try:
            date_part = os.path.basename(backup_file).replace(f"{s_id_safe}_", "").replace(".pkl", "")
            backup_date = datetime.strptime(date_part, '%Y%m%d').date()
            if backup_date < start_date:
                with open(backup_file, 'rb') as f:
                    profile_to_restore = pickle.load(f)
                backup_to_keep = backup_file
                break
        except (ValueError, IndexError):
            continue

    # 2. 메인 프로필을 복원할 프로필로 덮어쓰기 (없으면 새로 생성)
    if profile_to_restore:
        with open(main_profile_path, 'wb') as f: pickle.dump(profile_to_restore, f)
    elif os.path.exists(main_profile_path):
        os.remove(main_profile_path) # 이전 백업이 없으면 처음부터 다시 시작

    # 3. start_date 이후의 모든 백업 파일 삭제
    for backup_file in backups:
        if backup_file != backup_to_keep:
            os.remove(backup_file)

    # 4. submissions.json에서 start_date 이후의 모든 관련 기록을 'pending'으로 변경
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except: db_data = []

    reprocess_count = 0
    for item in db_data:
        if (item.get('student_name') == s_name and item.get('phone_suffix') == s_phone and item.get('subject') == s_subj):
            try:
                submission_date = datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).date()
                if submission_date >= start_date:
                    item['status'] = 'pending'
                    item.pop('processed_at', None)
                    reprocess_count += 1
            except:
                continue
    
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)

    return jsonify({"message": f"'{student_id}' 학생의 {start_date_str}부터의 모든 데이터가 재처리 대기 상태로 변경되었습니다. 총 {reprocess_count}개 기록이 재설정되었습니다."})


# --- 데이터 조회 및 기타 관리 API (일부 수정) ---
@app.route('/api/calendar/events', methods=['GET'])
def get_calendar_events():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    start_str, end_str = request.args.get('start'), request.args.get('end'); events_to_show = defaultdict(set)
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: 
            # [변경] 폐강된 수업은 캘린더에 표시하지 않음
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
                    # [신규] 반환 데이터에 student_id 추가
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
    
@app.route('/api/reprocess/<int:submission_id>', methods=['POST'])
def request_reprocessing(submission_id):
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except: return jsonify({"error": "파일을 찾을 수 없습니다."}), 404
    found = False
    for item in db_data:
        if item.get('id') == submission_id: item['status'] = 'pending'; item.pop('processed_at', None); found = True; break
    if not found: return jsonify({"error": "데이터를 찾을 수 없습니다."}), 404
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)
    return jsonify({"message": f"ID {submission_id}번 데이터가 '재처리 대기' 상태로 변경되었습니다."})

@app.route('/api/students', methods=['GET'])
def get_all_students():
    # [변경] 이 함수는 이제 사용되지 않을 수 있지만, 호환성을 위해 유지.
    # [변경] 재계산 기능이 다른 방식으로 구현됨.
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    students = set()
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
        for item in db_data:
            if all(k in item for k in ['student_name', 'phone_suffix', 'subject']):
                students.add(f"{item['student_name']}({item['phone_suffix']})_{item['subject']}")
    except: pass
    return jsonify(sorted(list(students)))

@app.route('/api/full-recalculate', methods=['POST'])
def full_recalculate():
    # [주의] 이 기능은 'recalculate_from_date'로 대체되었음.
    # 하지만 기존 UI 와의 호환성을 위해 남겨두되, 모든 기록을 리셋하도록 동작
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    student_id = request.get_json().get('student_id');
    if not student_id: return jsonify({"error": "학생 ID가 필요합니다."}), 400
    
    s_name, s_phone, s_subj = (re.match(r"(.+?)\((\d{4})\)_(.+)", student_id) or (None, None, None)).groups()
    
    # [변경] 서버에 저장된 pkl 파일과 백업을 삭제
    subject_dir, backup_dir, main_profile_path = get_student_paths(s_subj, student_id)
    if os.path.exists(main_profile_path): os.remove(main_profile_path)
    if os.path.exists(backup_dir): shutil.rmtree(backup_dir) # 백업 폴더 전체 삭제
        
    recalculated_count = 0
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
        for item in db_data:
            if (item.get('student_name') == s_name and item.get('phone_suffix') == s_phone and item.get('subject') == s_subj):
                item['status'] = 'pending'; item.pop('processed_at', None); recalculated_count += 1
        with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)
    except: pass
    return jsonify({"message": f"'{student_id}' 학생의 모든 데이터가 리셋되었습니다. 총 {recalculated_count}개의 기록이 재처리 대기 상태로 변경되었습니다."})
    

# --- 전체 데이터 백업 API (수정) ---
@app.route('/api/backup/download', methods=['GET'])
def download_full_backup():
    if not is_admin_session(): return "권한이 없습니다.", 401
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        # [변경] 백업 대상 경로에 STUDENT_DB_DIRECTORY 와 TEMPLATES_DB_FILE 추가
        paths_to_backup = [DB_FILE, FORMS_DB_FILE, TEMPLATES_DB_FILE, STUDENT_DB_DIRECTORY]
        for path in paths_to_backup:
            if not os.path.exists(path): continue
            if os.path.isfile(path):
                zf.write(path, os.path.basename(path))
            elif os.path.isdir(path):
                # [변경] os.walk를 사용하여 하위 모든 디렉토리와 파일을 포함
                for root, _, files in os.walk(path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # [변경] DATA_DIR 기준 상대 경로로 압축 파일 내 경로 설정
                        archive_name = os.path.relpath(file_path, DATA_DIR)
                        zf.write(file_path, archive_name)
    memory_file.seek(0)
    backup_filename = f"backup_{datetime.now(KST).strftime('%Y-%m-%d_%H%M')}.zip"
    return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name=backup_filename)

if __name__ == '__main__':
    init_all_dbs()
    app.run(host='0.0.0.0', port=5000, debug=False)