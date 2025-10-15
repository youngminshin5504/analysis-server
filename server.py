# --- 필요한 라이브러리 불러오기 ---
from flask import Flask, request, jsonify, render_template
import json
import os
from datetime import datetime

# --- Flask 앱 초기화 ---
app = Flask(__name__, template_folder='.')

# --- 데이터 저장을 위한 설정 ---
DB_FILE = 'submissions.json'
# [중요] 보안을 위한 API 비밀 키. 실제 운영 시에는 환경 변수를 사용하는 것이 더 안전합니다.
# 이 키는 외부로 절대 노출되면 안 됩니다.
API_SECRET_KEY = os.getenv("API_KEY", "MySuperSecretKey123!")

# --- 데이터베이스 파일 초기화 함수 ---
def init_db():
    """ 서버가 처음 시작될 때 데이터 저장 파일이 없으면 새로 만들어주는 함수 """
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        print(f"데이터 파일 '{DB_FILE}'을 생성했습니다.")

# --- API 엔드포인트(URL 경로) 정의 ---

# 조교가 접속하는 페이지는 보안이 필요 없습니다.
@app.route('/', methods=['GET'])
def index():
    """ 사용자가 웹 브라우저로 접속하면 보게 될 메인 페이지를 렌더링합니다. """
    return render_template('index.html')

# 조교가 데이터를 제출하는 것도 보안이 필요 없습니다.
@app.route('/submit', methods=['POST'])
def submit_data():
    """ 학생 답안 데이터를 제출받아 저장하는 API """
    data = request.get_json()
    print(f"새로운 데이터 수신: {data.get('student_name')}")
    
    db_data = [] # 우선 빈 리스트로 시작합니다.
    try:
        # [수정] 먼저 파일을 읽어보려고 시도합니다.
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
    except FileNotFoundError:
        # [수정] 만약 파일이 없다는 에러(FileNotFoundError)가 발생하면,
        # 아무것도 하지 않고 그냥 지나갑니다. (db_data는 여전히 빈 리스트)
        print(f"'{DB_FILE}' 파일이 존재하지 않아 새로 생성합니다.")
    except json.JSONDecodeError:
        # [추가] 파일은 있지만 내용이 비어있거나 깨졌을 경우를 대비합니다.
        print(f"'{DB_FILE}' 파일 내용이 비어있어 새로 시작합니다.")
        db_data = []

    # 새로 받은 데이터에 추가 정보(ID, 상태, 제출 시간)를 붙여줍니다.
    submission_id = len(db_data) + 1
    data['id'] = submission_id
    data['status'] = 'pending'
    data['submitted_at'] = datetime.now().isoformat()
    db_data.append(data)

    # 변경된 내용을 다시 데이터베이스 파일에 덮어씁니다.
    # 이 때는 'w'(쓰기) 모드이므로 파일이 없으면 자동으로 새로 만듭니다.
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db_data, f, ensure_ascii=False, indent=2)

    return jsonify({"message": "데이터가 성공적으로 제출되었습니다.", "id": submission_id}), 201

# --- [중요] 지금부터는 관리자만 접근해야 하는 API 이므로 보안 체크를 추가합니다. ---

@app.route('/pending-data', methods=['GET'])
def get_pending_data():
    """ '처리 대기 중' 상태인 모든 데이터를 반환하는 API (보안 적용) """
    # [보안] 요청 헤더에 포함된 API 키를 확인합니다.
    request_key = request.headers.get('X-API-KEY')
    if request_key != API_SECRET_KEY:
        print(f"보안 경고: 잘못된 API 키로 접근 시도됨 - {request_key}")
        return jsonify({"error": "Unauthorized"}), 401 # 허가되지 않은 접근은 거부

    print("\n[보안 통과] 분석 스크립트로부터 처리 대기 데이터 요청을 받았습니다.")
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        db_data = json.load(f)
    
    pending_list = [item for item in db_data if item.get('status') == 'pending']
    print(f"총 {len(pending_list)}개의 처리 대기 데이터를 전송합니다.")
    return jsonify(pending_list)

@app.route('/mark-processed', methods=['POST'])
def mark_processed():
    """ 지정된 ID들의 상태를 'processed'로 변경하는 API (보안 적용) """
    # [보안] 여기도 똑같이 API 키를 확인합니다.
    request_key = request.headers.get('X-API-KEY')
    if request_key != API_SECRET_KEY:
        print(f"보안 경고: 잘못된 API 키로 상태 변경 시도됨 - {request_key}")
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    processed_ids = data.get('ids', [])
    print(f"\n[보안 통과] {processed_ids} 항목들을 '처리 완료' 상태로 변경 요청을 받았습니다.")

    with open(DB_FILE, 'r', encoding='utf-8') as f:
        db_data = json.load(f)

    for item in db_data:
        if item.get('id') in processed_ids:
            item['status'] = 'processed'
            item['processed_at'] = datetime.now().isoformat()
    
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db_data, f, ensure_ascii=False, indent=2)

    print("상태 변경 완료.")
    return jsonify({"message": f"{len(processed_ids)}개의 항목이 처리 완료로 표시되었습니다."})

# --- 서버 실행 ---
# 로컬 테스트 시에는 `python server.py`로 실행할 수 있습니다.
# 웹 배포 시에는 gunicorn 같은 전문 WSGI 서버가 `app` 객체를 직접 실행합니다.
if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)