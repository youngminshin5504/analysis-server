# --- 필요한 라이브러리 및 설정 (이전과 동일) ---
from flask import Flask, request, jsonify, render_template
import json, os
from datetime import datetime
from collections import defaultdict
app = Flask(__name__, template_folder='.')
DATA_DIR = "/var/data"
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)
DB_FILE = os.path.join(DATA_DIR, "submissions.json")
FORMS_DB_FILE = os.path.join(DATA_DIR, "forms.json")
API_SECRET_KEY = os.getenv("API_KEY", "MySuperSecretKey123!")
def init_all_dbs():
    for db_path in [DB_FILE, FORMS_DB_FILE]:
        if not os.path.exists(db_path):
            with open(db_path, 'w', encoding='utf-8') as f: json.dump([], f, ensure_ascii=False, indent=2)

# --- [변경] 달력(Calendar) 데이터 조회를 위한 API 수정 ---

@app.route('/api/calendar/events', methods=['GET'])
def get_calendar_events():
    """ 
    특정 월에 제출된 데이터를 '날짜'와 '폼'으로 그룹화하여 
    FullCalendar 이벤트 목록으로 반환합니다. (관리자용)
    """
    if request.headers.get('X-API-KEY') != API_SECRET_KEY: return jsonify({"error": "Unauthorized"}), 401
    
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    
    events_to_show = defaultdict(set)
    try:
        # 폼 정보를 미리 불러와 id -> name 맵을 만듭니다.
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f:
            forms_info = {form['id']: form.get('name', '이름 없는 양식') for form in json.load(f)}
            
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
            
        for item in db_data:
            submitted_date = item.get('submitted_at', '').split('T')[0]
            if start_str <= submitted_date < end_str:
                form_id = item.get('form_id')
                if form_id:
                    # (날짜, 폼ID) 쌍으로 유일한 이벤트를 기록
                    events_to_show[submitted_date].add(form_id)

    except (FileNotFoundError, json.JSONDecodeError):
        pass
        
    # FullCalendar 이벤트 객체 목록 생성
    calendar_events = []
    for date_str, form_ids in events_to_show.items():
        for form_id in form_ids:
            form_name = forms_info.get(form_id, "알 수 없는 양식")
            calendar_events.append({
                "title": form_name,
                "start": date_str,
                "extendedProps": { # 클릭 시 사용할 추가 데이터
                    "formId": form_id
                }
            })
            
    return jsonify(calendar_events)

# --- (이하 나머지 모든 API 함수들은 이전 답변과 완전히 동일합니다. 생략 없이 포함) ---
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
    if request.headers.get('X-API-KEY') != API_SECRET_KEY: return jsonify({"error": "Unauthorized"}), 401
    new_form_data = request.get_json(); forms = []
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): pass
    forms.append(new_form_data)
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f: json.dump(forms, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "새로운 양식이 성공적으로 저장되었습니다."}), 201

@app.route('/api/forms/<form_id>', methods=['DELETE'])
def delete_form(form_id):
    if request.headers.get('X-API-KEY') != API_SECRET_KEY: return jsonify({"error": "Unauthorized"}), 401
    forms = []
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f: forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): pass
    forms_after_delete = [form for form in forms if form.get('id') != form_id]
    if len(forms) == len(forms_after_delete): return jsonify({"error": "해당 ID의 양식을 찾을 수 없습니다."}), 404
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f: json.dump(forms_after_delete, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "양식이 성공적으로 삭제되었습니다."})

@app.route('/submit', methods=['POST'])
def submit_data():
    data = request.get_json(); print(f"새로운 데이터 수신: {data.get('student_name')}"); db_data = []
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): print(f"'{DB_FILE}' 파일을 새로 생성합니다.")
    submission_id = (db_data[-1]['id'] + 1) if db_data else 1
    data['id'] = submission_id; data['status'] = 'pending'; data['submitted_at'] = datetime.now().isoformat(); db_data.append(data)
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "데이터가 성공적으로 제출되었습니다.", "id": submission_id}), 201

@app.route('/pending-data', methods=['GET'])
def get_pending_data():
    if request.headers.get('X-API-KEY') != API_SECRET_KEY: return jsonify({"error": "Unauthorized"}), 401
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): db_data = []
    return jsonify([item for item in db_data if item.get('status') == 'pending'])

@app.route('/mark-processed', methods=['POST'])
def mark_processed():
    if request.headers.get('X-API-KEY') != API_SECRET_KEY: return jsonify({"error": "Unauthorized"}), 401
    processed_ids = request.get_json().get('ids', []);
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): db_data = []
    for item in db_data:
        if item.get('id') in processed_ids: item['status'] = 'processed'; item['processed_at'] = datetime.now().isoformat()
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)
    return jsonify({"message": f"{len(processed_ids)}개 항목이 처리 완료로 표시되었습니다."})
    
@app.route('/api/data/by-date-form/<string:date_str>/<string:form_id>', methods=['GET'])
def get_data_by_date_and_form(date_str, form_id):
    if request.headers.get('X-API-KEY') != API_SECRET_KEY: return jsonify({"error": "Unauthorized"}), 401
    matching_data = []
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
        for item in db_data:
            if item.get('submitted_at', '').startswith(date_str) and item.get('form_id') == form_id: matching_data.append(item)
    except (FileNotFoundError, json.JSONDecodeError): pass
    return jsonify(matching_data)
    
@app.route('/api/reprocess/<int:submission_id>', methods=['POST'])
def request_reprocessing(submission_id):
    if request.headers.get('X-API-KEY') != API_SECRET_KEY: return jsonify({"error": "Unauthorized"}), 401
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return jsonify({"error": "제출 데이터 파일을 찾을 수 없습니다."}), 404
    found = False
    for item in db_data:
        if item.get('id') == submission_id: item['status'] = 'pending'; item.pop('processed_at', None); found = True; break
    if not found: return jsonify({"error": "해당 ID의 제출 데이터를 찾을 수 없습니다."}), 404
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(db_data, f, ensure_ascii=False, indent=2)
    return jsonify({"message": f"ID {submission_id}번 데이터가 '재처리 대기' 상태로 변경되었습니다."})

if __name__ == '__main__': init_all_dbs(); app.run(host='0.0.0.0', port=5000)