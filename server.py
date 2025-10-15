# --- 필요한 라이브러리 불러오기 ---
from flask import Flask, request, jsonify, render_template
import json
import os
from datetime import datetime
from collections import defaultdict
import pytz  # 시간대 처리를 위한 라이브러리

# --- Flask 앱 초기화 및 설정 ---
app = Flask(__name__, template_folder='.')
DATA_DIR = "/var/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_FILE = os.path.join(DATA_DIR, "submissions.json")
FORMS_DB_FILE = os.path.join(DATA_DIR, "forms.json")
API_SECRET_KEY = os.getenv("API_KEY", "MySuperSecretKey123!")
KST = pytz.timezone('Asia/Seoul')  # 한국 시간대 객체 생성

# --- 데이터베이스 파일 초기화 함수 ---
def init_all_dbs():
    """ 서버가 처음 시작될 때 모든 데이터 저장 파일이 없으면 새로 만들어주는 함수 """
    for db_path in [DB_FILE, FORMS_DB_FILE]:
        if not os.path.exists(db_path):
            with open(db_path, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            print(f"데이터 파일 '{db_path}'을 생성했습니다.")

# --- API 엔드포인트(URL 경로) 정의 ---

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

# --- 폼(Form) 관리를 위한 API들 ---

@app.route('/api/forms', methods=['GET'])
def get_forms():
    """ 저장된 모든 폼의 목록을 반환합니다. (누구나 조회 가능) """
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f:
            forms = json.load(f)
        return jsonify(forms)
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify([])

@app.route('/api/forms', methods=['POST'])
def add_form():
    """ 새로운 폼을 추가합니다. (관리자만 가능) """
    if request.headers.get('X-API-KEY') != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    new_form_data = request.get_json()
    forms = []
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f:
            forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    
    forms.append(new_form_data)
    
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(forms, f, ensure_ascii=False, indent=2)
        
    return jsonify({"message": "새로운 양식이 성공적으로 저장되었습니다."}), 201

@app.route('/api/forms/<form_id>', methods=['DELETE'])
def delete_form(form_id):
    """ 특정 ID의 폼을 삭제합니다. (관리자만 가능) """
    if request.headers.get('X-API-KEY') != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    forms = []
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f:
            forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    
    forms_after_delete = [form for form in forms if form.get('id') != form_id]
    
    if len(forms) == len(forms_after_delete):
        return jsonify({"error": "해당 ID의 양식을 찾을 수 없습니다."}), 404
        
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(forms_after_delete, f, ensure_ascii=False, indent=2)
        
    return jsonify({"message": "양식이 성공적으로 삭제되었습니다."})

# --- 제출(Submission) 데이터 관리를 위한 API들 ---

@app.route('/submit', methods=['POST'])
def submit_data():
    """ 
    학생 답안 데이터를 제출받아 저장합니다.
    동일 학생, 동일 시험, 동일 날짜에 대한 중복 제출을 방지(덮어쓰기)합니다.
    """
    data = request.get_json()
    print(f"새로운 데이터 수신: {data.get('student_name')}")
    db_data = []
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"'{DB_FILE}' 파일을 새로 생성합니다.")
    
    now_kst = datetime.now(KST)
    today_kst_str = now_kst.strftime('%Y-%m-%d')
    
    key_to_check = (today_kst_str, data.get('student_name'), data.get('phone_suffix'), data.get('form_id'))
    
    found_and_updated = False
    for i, item in enumerate(db_data):
        try:
            item_date_str = datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            continue # 날짜 형식이 잘못된 데이터는 건너뜀
            
        item_key = (item_date_str, item.get('student_name'), item.get('phone_suffix'), item.get('form_id'))
        
        if item_key == key_to_check:
            print(f"중복 제출 발견: ID {item.get('id')}번 데이터를 덮어씁니다.")
            data['id'] = item['id']
            data['status'] = 'pending'
            data['submitted_at'] = now_kst.isoformat()
            db_data[i] = data
            found_and_updated = True
            break
            
    if not found_and_updated:
        submission_id = (db_data[-1]['id'] + 1) if db_data else 1
        data['id'] = submission_id
        data['status'] = 'pending'
        data['submitted_at'] = now_kst.isoformat()
        db_data.append(data)

    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db_data, f, ensure_ascii=False, indent=2)
        
    return jsonify({"message": "데이터가 성공적으로 제출되었습니다.", "id": data['id']}), 201

@app.route('/pending-data', methods=['GET'])
def get_pending_data():
    """ '처리 대기 중' 상태인 모든 데이터를 반환합니다. (관리자용) """
    if request.headers.get('X-API-KEY') != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        db_data = []
    return jsonify([item for item in db_data if item.get('status') == 'pending'])

@app.route('/mark-processed', methods=['POST'])
def mark_processed():
    """ 지정된 ID 목록의 데이터 상태를 'processed'로 변경합니다. (관리자용) """
    if request.headers.get('X-API-KEY') != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    processed_ids = request.get_json().get('ids', [])
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        db_data = []
    now_kst_iso = datetime.now(KST).isoformat()
    for item in db_data:
        if item.get('id') in processed_ids:
            item['status'] = 'processed'
            item['processed_at'] = now_kst_iso
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db_data, f, ensure_ascii=False, indent=2)
    return jsonify({"message": f"{len(processed_ids)}개 항목이 처리 완료로 표시되었습니다."})

# --- 달력(Calendar) 및 재처리 데이터 조회를 위한 API들 ---

@app.route('/api/calendar/events', methods=['GET'])
def get_calendar_events():
    """ 특정 월에 제출된 데이터를 '날짜'와 '폼'으로 그룹화하여 FullCalendar 이벤트 목록으로 반환합니다. """
    if request.headers.get('X-API-KEY') != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    start_str, end_str = request.args.get('start'), request.args.get('end')
    events_to_show = defaultdict(set)
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f:
            forms_info = {form['id']: form.get('name', '이름 없는 양식') for form in json.load(f)}
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
        for item in db_data:
            try:
                submitted_date = datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).strftime('%Y-%m-%d')
                if start_str <= submitted_date < end_str:
                    form_id = item.get('form_id')
                    if form_id: events_to_show[submitted_date].add(form_id)
            except (ValueError, TypeError):
                continue
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    calendar_events = []
    for date_str, form_ids in events_to_show.items():
        for form_id in form_ids:
            form_name = forms_info.get(form_id, "알 수 없는 양식")
            calendar_events.append({"title": form_name, "start": date_str, "extendedProps": {"formId": form_id}})
    return jsonify(calendar_events)

@app.route('/api/data/by-date-form/<string:date_str>/<string:form_id>', methods=['GET'])
def get_data_by_date_and_form(date_str, form_id):
    """ 특정 날짜, 특정 폼 ID에 해당하는 모든 학생 데이터를 반환합니다. """
    if request.headers.get('X-API-KEY') != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    matching_data = []
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
        for item in db_data:
            try:
                item_date_str = datetime.fromisoformat(item.get('submitted_at')).astimezone(KST).strftime('%Y-%m-%d')
                if item_date_str == date_str and item.get('form_id') == form_id:
                    matching_data.append(item)
            except (ValueError, TypeError):
                continue
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return jsonify(matching_data)
    
@app.route('/api/reprocess/<int:submission_id>', methods=['POST'])
def request_reprocessing(submission_id):
    """ 특정 ID의 제출 데이터 상태를 'pending'으로 되돌립니다. """
    if request.headers.get('X-API-KEY') != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({"error": "제출 데이터 파일을 찾을 수 없습니다."}), 404
    found = False
    for item in db_data:
        if item.get('id') == submission_id:
            item['status'] = 'pending'
            item.pop('processed_at', None)
            found = True
            break
    if not found:
        return jsonify({"error": "해당 ID의 제출 데이터를 찾을 수 없습니다."}), 404
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db_data, f, ensure_ascii=False, indent=2)
    return jsonify({"message": f"ID {submission_id}번 데이터가 '재처리 대기' 상태로 변경되었습니다."})

# --- 서버 실행 ---
if __name__ == '__main__':
    init_all_dbs()
    app.run(host='0.0.0.0', port=5000, debug=False)