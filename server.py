# --- 필요한 라이브러리 불러오기 ---
from flask import Flask, request, jsonify, render_template, session
from flask_session import Session # 세션 관리 라이브러리
import json
import os
import re
import glob
from datetime import datetime
from collections import defaultdict
import pytz

# --- Flask 앱 초기화 및 설정 ---
app = Flask(__name__, template_folder='.')
app.config["SECRET_KEY"] = os.getenv("SESSION_KEY", "a_super_secret_key_for_session_management_!@#$")
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "/var/data/sessions" # 세션 파일도 영구 저장소에 보관
Session(app)

# --- 경로 및 상수 설정 ---
DATA_DIR = "/var/data"
STUDENT_DB_DIRECTORY = os.path.join(DATA_DIR, "students")
STUDENT_BACKUP_DIRECTORY = os.path.join(STUDENT_DB_DIRECTORY, "backups")
DB_FILE = os.path.join(DATA_DIR, "submissions.json")
FORMS_DB_FILE = os.path.join(DATA_DIR, "forms.json")
API_SECRET_KEY = os.getenv("API_KEY", "MySuperSecretKey123!") # run_analysis.py 와의 통신용
ADMIN_PASSWORD = "dusrntlf"
KST = pytz.timezone('Asia/Seoul')

def init_all_dbs():
    """ 서버가 처음 시작될 때 모든 데이터 파일과 디렉터리가 없으면 새로 생성합니다. """
    paths_to_create = [DATA_DIR, STUDENT_DB_DIRECTORY, STUDENT_BACKUP_DIRECTORY, app.config["SESSION_FILE_DIR"]]
    for p in paths_to_create:
        if not os.path.exists(p): os.makedirs(p)
    for db_path in [DB_FILE, FORMS_DB_FILE]:
        if not os.path.exists(db_path):
            with open(db_path, 'w', encoding='utf-8') as f: json.dump([], f, ensure_ascii=False, indent=2)

# --- 인증 관련 API 및 함수 ---
def is_admin_session():
    """ 웹 UI 사용자가 관리자로 로그인했는지 확인 (세션 기반) """
    return session.get('is_admin', False)

def is_admin_apikey():
    """ 외부 스크립트(run_analysis.py)가 올바른 API 키로 요청했는지 확인 """
    return request.headers.get('X-API-KEY') == API_SECRET_KEY

@app.route('/api/login', methods=['POST'])
def login():
    password = request.json.get('password')
    if password == ADMIN_PASSWORD:
        session['is_admin'] = True
        return jsonify({"message": "로그인 성공"})
    else:
        return jsonify({"error": "비밀번호가 틀렸습니다."}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('is_admin', None)
    return jsonify({"message": "로그아웃 성공"})

@app.route('/api/auth-status', methods=['GET'])
def auth_status():
    return jsonify({"is_admin": is_admin_session()})

# --- API 엔드포인트 ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/forms', methods=['GET'])
def get_forms():
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
        return jsonify(forms)
    except (FileNotFoundError, json.JSONDecodeError): return jsonify([])

@app.route('/api/forms', methods=['POST'])
def add_form():
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    new_form_data = request.get_json(); forms = []
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): pass
    forms.append(new_form_data)
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f: json.dump(forms, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "새로운 수업이 성공적으로 저장되었습니다."}), 201

@app.route('/api/forms/<form_id>', methods=['DELETE'])
def delete_form(form_id):
    if not is_admin_session(): return jsonify({"error": "권한이 없습니다."}), 401
    forms = []
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): pass
    forms_after_delete = [form for form in forms if form.get('id') != form_id]
    if len(forms) == len(forms_after_delete): return jsonify({"error": "해당 ID의 수업을 찾을 수 없습니다."}), 404
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f: json.dump(forms_after_delete, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "수업이 성공적으로 삭제되었습니다."})

@app.route('/submit', methods=['POST'])
def submit_data():
    data = request.get_json(); print(f"새로운 데이터 수신: {data.get('student_name')}"); db_data = []
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): print(f"'{DB_FILE}' 파일을 새로 생성합니다.")
    now_kst = datetime.now(KST); today_kst_str = now_kst.strftime('%Y-%m-%d')
    key_to_check = (today_kst_str, data.get('student_name'), data.get('phone_suffix'), data.get('form_id'))
    found_and_updated = False
    for i, item in enumerate(db_data):
        try:
            item_date_str = datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).strftime('%Y-%m-%d')
            item_key = (item_date_str, item.get('student_name'), item.get('phone_suffix'), item.get('form_id'))
            if item_key == key_to_check:
                data['id'] = item['id']; data['status'] = 'pending'; data['submitted_at'] = now_kst.isoformat()
                db_data[i] = data; found_and_updated = True; break
        except (ValueError, TypeError): continue
    if not found_and_updated:
        submission_id = (db_data[-1]['id'] + 1) if db_data else 1
        data['id'] = submission_id; data['status'] = 'pending'; data['submitted_at'] = now_kst.isoformat(); db_data.append(data)
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "데이터가 성공적으로 제출되었습니다.", "id": data['id']}), 201

@app.route('/pending-data', methods=['GET'])
def get_pending_data():
    if not is_admin_apikey(): return jsonify({"error": "Unauthorized"}), 401 # API 키로만 접근 가능
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): db_data = []
    return jsonify([item for item in db_data if item.get('status') == 'pending'])

@app.route('/mark-processed', methods=['POST'])
def mark_processed():
    if not is_admin_apikey(): return jsonify({"error": "Unauthorized"}), 401 # API 키로만 접근 가능
    processed_ids = request.get_json().get('ids', []);
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): db_data = []
    now_kst_iso = datetime.now(KST).isoformat()
    for item in db_data:
        if item.get('id') in processed_ids: item['status'] = 'processed'; item['processed_at'] = now_kst_iso
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)
    return jsonify({"message": f"{len(processed_ids)}개 항목이 처리 완료로 표시되었습니다."})

@app.route('/api/calendar/events', methods=['GET'])
def get_calendar_events():
    if not is_admin_session(): return jsonify({"error": "Unauthorized"}), 401
    start_str, end_str = request.args.get('start'), request.args.get('end'); events_to_show = defaultdict(set)
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms_info = {form['id']: form.get('name', 'N/A') for form in json.load(f)}
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
        for item in db_data:
            try:
                submitted_date = datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).strftime('%Y-%m-%d')
                if start_str <= submitted_date < end_str and item.get('form_id'):
                    events_to_show[submitted_date].add(item.get('form_id'))
            except (ValueError, TypeError): continue
    except (FileNotFoundError, json.JSONDecodeError): pass
    calendar_events = [{"title": forms_info.get(form_id, "알 수 없는 수업"), "start": date_str, "extendedProps": {"formId": form_id}} for date_str, form_ids in events_to_show.items() for form_id in form_ids]
    return jsonify(calendar_events)

@app.route('/api/data/by-date-form/<string:date_str>/<string:form_id>', methods=['GET'])
def get_data_by_date_and_form(date_str, form_id):
    if not is_admin_session(): return jsonify({"error": "Unauthorized"}), 401
    latest_submissions = {}
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
        for item in db_data:
            try:
                if datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).strftime('%Y-%m-%d') == date_str and item.get('form_id') == form_id:
                    student_key = (item.get('student_name'), item.get('phone_suffix'))
                    if student_key not in latest_submissions or item.get('submitted_at') > latest_submissions[student_key].get('submitted_at'):
                        latest_submissions[student_key] = item
            except (ValueError, TypeError): continue
    except (FileNotFoundError, json.JSONDecodeError): pass
    return jsonify(list(latest_submissions.values()))

@app.route('/api/submission/<int:submission_id>', methods=['GET'])
def get_submission_details(submission_id):
    if not is_admin_session(): return jsonify({"error": "Unauthorized"}), 401
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
        for item in db_data:
            if item.get('id') == submission_id: return jsonify(item)
    except (FileNotFoundError, json.JSONDecodeError): pass
    return jsonify({"error": "해당 ID의 데이터를 찾을 수 없습니다."}), 404

@app.route('/api/submission/<int:submission_id>', methods=['DELETE'])
def delete_submission(submission_id):
    if not is_admin_session(): return jsonify({"error": "Unauthorized"}), 401
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return jsonify({"error": "제출 데이터 파일을 찾을 수 없습니다."}), 404
    initial_length = len(db_data)
    db_data_after_delete = [item for item in db_data if item.get('id') != submission_id]
    if len(db_data_after_delete) == initial_length: return jsonify({"error": "해당 ID의 제출 기록을 찾을 수 없습니다."}), 404
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data_after_delete, f, ensure_ascii=False, indent=2)
    return jsonify({"message": f"ID {submission_id}번 제출 기록이 영구적으로 삭제되었습니다."})
    
@app.route('/api/reprocess/<int:submission_id>', methods=['POST'])
def request_reprocessing(submission_id):
    if not is_admin_session(): return jsonify({"error": "Unauthorized"}), 401
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return jsonify({"error": "제출 데이터 파일을 찾을 수 없습니다."}), 404
    found = False
    for item in db_data:
        if item.get('id') == submission_id: item['status'] = 'pending'; item.pop('processed_at', None); found = True; break
    if not found: return jsonify({"error": "해당 ID의 제출 데이터를 찾을 수 없습니다."}), 404
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)
    return jsonify({"message": f"ID {submission_id}번 데이터가 '재처리 대기' 상태로 변경되었습니다."})

@app.route('/api/students', methods=['GET'])
def get_all_students():
    if not is_admin_session(): return jsonify({"error": "Unauthorized"}), 401
    students = set()
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
        for item in db_data:
            if all(k in item for k in ['student_name', 'phone_suffix', 'subject']):
                students.add(f"{item['student_name']}({item['phone_suffix']})_{item['subject']}")
    except (FileNotFoundError, json.JSONDecodeError): pass
    return jsonify(sorted(list(students)))

@app.route('/api/full-recalculate', methods=['POST'])
def full_recalculate():
    if not is_admin_session(): return jsonify({"error": "Unauthorized"}), 401
    student_id = request.get_json().get('student_id');
    if not student_id: return jsonify({"error": "학생 ID가 필요합니다."}), 400
    s_name, s_phone, s_subj = (re.match(r"(.+?)\((\d{4})\)_(.+)", student_id) or (None, None, None)).groups()
    s_id_safe = student_id.replace('/', '_')
    main_profile_path = os.path.join(STUDENT_DB_DIRECTORY, f"{s_id_safe}.pkl")
    if os.path.exists(main_profile_path): os.remove(main_profile_path)
    for f in glob.glob(os.path.join(STUDENT_BACKUP_DIRECTORY, f"{s_id_safe}_*.pkl")): os.remove(f)
    recalculated_count = 0
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
        for item in db_data:
            if (item.get('student_name') == s_name and item.get('phone_suffix') == s_phone and item.get('subject') == s_subj):
                item['status'] = 'pending'; item.pop('processed_at', None); recalculated_count += 1
        with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)
    except (FileNotFoundError, json.JSONDecodeError): pass
    return jsonify({"message": f"'{student_id}' 학생의 모든 데이터가 리셋되었습니다. 총 {recalculated_count}개의 기록이 재처리 대기 상태로 변경되었습니다."})

if __name__ == '__main__':
    init_all_dbs()
    app.run(host='0.0.0.0', port=5000, debug=False)