# --- 필요한 라이브러리 불러오기 ---
from flask import Flask, request, jsonify, render_template
import json
import os
from datetime import datetime

# --- Flask 앱 초기화 ---
app = Flask(__name__, template_folder='.')

# --- 데이터 저장을 위한 설정: Persistent Disk 경로 사용 ---
DATA_DIR = "/var/data" 
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_FILE = os.path.join(DATA_DIR, "submissions.json")
FORMS_DB_FILE = os.path.join(DATA_DIR, "forms.json")
API_SECRET_KEY = os.getenv("API_KEY", "MySuperSecretKey123!")

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
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f:
            forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        forms = []
    
    forms.append(new_form_data)
    
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(forms, f, ensure_ascii=False, indent=2)
        
    return jsonify({"message": "새로운 양식이 성공적으로 저장되었습니다."}), 201

@app.route('/api/forms/<form_id>', methods=['DELETE'])
def delete_form(form_id):
    """ 특정 ID의 폼을 삭제합니다. (관리자만 가능) """
    if request.headers.get('X-API-KEY') != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        with open(FORMS_DB_FILE, 'r', encoding='utf-8') as f:
            forms = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        forms = []
    
    forms_after_delete = [form for form in forms if form.get('id') != form_id]
    
    if len(forms) == len(forms_after_delete):
        return jsonify({"error": "해당 ID의 양식을 찾을 수 없습니다."}), 404
        
    with open(FORMS_DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(forms_after_delete, f, ensure_ascii=False, indent=2)
        
    return jsonify({"message": "양식이 성공적으로 삭제되었습니다."})

# --- 제출(Submission) 데이터 관리를 위한 API들 ---

@app.route('/submit', methods=['POST'])
def submit_data():
    """ 학생 답안 데이터를 제출받아 저장합니다. """
    data = request.get_json()
    print(f"새로운 데이터 수신: {data.get('student_name')}")
    db_data = []
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"'{DB_FILE}' 파일을 새로 생성합니다.")
    
    submission_id = len(db_data) + 1
    data['id'] = submission_id
    data['status'] = 'pending'
    data['submitted_at'] = datetime.now().isoformat()
    db_data.append(data)
    
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db_data, f, ensure_ascii=False, indent=2)
        
    return jsonify({"message": "데이터가 성공적으로 제출되었습니다.", "id": submission_id}), 201

@app.route('/pending-data', methods=['GET'])
def get_pending_data():
    """ '처리 대기 중' 상태인 모든 데이터를 반환합니다. (관리자용) """
    if request.headers.get('X-API-KEY') != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
        
    print("\n[보안 통과] 처리 대기 데이터 요청 수신.")
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        db_data = []
        
    pending_list = [item for item in db_data if item.get('status') == 'pending']
    return jsonify(pending_list)

@app.route('/mark-processed', methods=['POST'])
def mark_processed():
    """ 지정된 ID 목록의 데이터 상태를 'processed'로 변경합니다. (관리자용) """
    if request.headers.get('X-API-KEY') != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
        
    processed_ids = request.get_json().get('ids', [])
    print(f"\n[보안 통과] {len(processed_ids)}개 항목 처리 완료 요청 수신.")
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        db_data = []
        
    for item in db_data:
        if item.get('id') in processed_ids:
            item['status'] = 'processed'
            item['processed_at'] = datetime.now().isoformat()
            
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db_data, f, ensure_ascii=False, indent=2)
        
    return jsonify({"message": f"{len(processed_ids)}개 항목이 처리 완료로 표시되었습니다."})

# --- 특정 학생 재처리를 위한 API들 ---

@app.route('/api/processed-today', methods=['GET'])
def get_processed_today():
    """ 오늘 날짜에 'processed' 상태가 된 모든 제출 데이터를 반환합니다. (관리자용) """
    if request.headers.get('X-API-KEY') != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    processed_list = []
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
        for item in db_data:
            if item.get('status') == 'processed' and item.get('processed_at', '').startswith(today_str):
                processed_list.append(item)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
        
    return jsonify(processed_list)

@app.route('/api/reprocess/<int:submission_id>', methods=['POST'])
def request_reprocessing(submission_id):
    """ 특정 ID의 제출 데이터 상태를 'pending'으로 되돌립니다. (관리자용) """
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
    app.run(host='0.0.0.0', port=5000, debug=False) # 배포 시에는 debug=False 권장