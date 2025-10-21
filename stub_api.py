from flask import Flask, request, jsonify, abort, Response
import datetime, uuid
import logging
from logging.handlers import RotatingFileHandler
import os
import sys

# --- 1. インターフェースマッピングの定義 (CSVより抽出) ---
# object値に紐づくIDと名称を正確に反映
INTERFACE_MAPPING = {
    "DeliveryTemp__c": {"id": "IF-630008", "name": "(EC)納車車両情報/車両"},
    "VehicleDefinition": {"id": "IF-630009", "name": "(EC)納車車両情報/車両定義"},
    "Product2": {"id": "IF-630010", "name": "(EC)納車車両情報/商品(車両)"},
    "Gurantee__c": {"id": "IF-630012", "name": "(EC)保険契約情報"},
    "ContractDeliveryTemp__c": {"id": "IF-630014", "name": "(EC)契約情報（プラン登録）"},
    "Examination__c": {"id": "IF-630015", "name": "(EC)契約情報（申込・審査）"},
}

# CSVファイルのマッピングと対応するファイル名 (拡張子を除く)
CSV_FILE_MAP = {
    "DeliveryTemp__c": "delivery_temp",
    "VehicleDefinition": "vehicle_definition",
    "Product2": "product2",
    "Gurantee__c": "gurantee",
    "ContractDeliveryTemp__c": "contract_delivery_temp",
    "Examination__c": "examination",
}

# CSVデータを格納するグローバル辞書
LOADED_CSV_DATA = {
    "success": {},
    "fail": {},
    "unproc": {}
}

# ジョブ状態を保存するストア
JOB_STORE = {}

# ベースパスを定義
BASE_PATH = '/services/data/v62.0/jobs/ingest'
# Composite API のパスを定義
COMPOSITE_PATH = '/services/data/v62.0/composite' 
# OAuth Token API のパスを定義 (新規)
OAUTH_TOKEN_PATH = '/services/oauth2/token'

# ジョブ処理完了までのGETポーリング回数 (3回目でJobComplete)
MAX_GET_COUNT = 3


app = Flask(__name__)

# --- 2. ロギング設定 ---
def setup_logging():
    # 既存のハンドラをクリア (Flaskのデフォルトハンドラを上書きするため)
    for handler in app.logger.handlers:
        app.logger.removeHandler(handler)
        
    # Job IDなどの情報を含めるためのカスタムフォーマット
    log_formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(job_info)s] %(message)s', 
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # ファイルハンドラ (ローテート設定)
    file_handler = RotatingFileHandler('stub_api.log', maxBytes=1024 * 1024 * 5, backupCount=5)
    file_handler.setFormatter(log_formatter)
    app.logger.addHandler(file_handler)

    # コンソールハンドラ (シンプルに出力)
    # コンソール用は job_info を含めず、シンプルなフォーマットにする
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    app.logger.addHandler(stream_handler)
    
    app.logger.setLevel(logging.DEBUG)
    
    # サーバー起動時やCSVロード時など、job_info が未定義のログのためにデフォルトを設定
    app.logger.info("Logging initialized.", extra={'job_info': 'BOOT'})

# --- 3. CSVファイルのロード ---
def load_csv_data():
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    
    # 6つのオブジェクト x 3つの結果タイプ = 18ファイルをロード
    for object_name, file_prefix in CSV_FILE_MAP.items():
        for result_type in ["success", "fail", "unproc"]:
            filename = f"{file_prefix}_{result_type}.csv"
            filepath = os.path.join(data_dir, filename)
            
            log_extra = {'job_info': 'LOAD'}

            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    LOADED_CSV_DATA[result_type][object_name] = content
                    app.logger.debug(f"Loaded {result_type} data for {object_name} from {filename}", extra=log_extra)
                except Exception as e:
                    app.logger.error(f"Failed to read CSV file {filepath}: {e}", extra=log_extra)
                    LOADED_CSV_DATA[result_type][object_name] = ""
            else:
                app.logger.warning(f"CSV file not found: {filepath}. Setting empty data.", extra=log_extra)
                LOADED_CSV_DATA[result_type][object_name] = ""
    app.logger.info(f"CSV loading complete. Total objects loaded: {len(CSV_FILE_MAP)}", extra={'job_info': 'BOOT'})


# --- ヘルパー関数: 共通認証チェックとロギング ---
# skip_auth 引数を追加し、OAuth API のように Authorization ヘッダーが不要なケースに対応
def check_auth_and_log(expected_content_type_prefix=None, skip_auth=False):
    # ロギングのための共通情報（ジョブIDなどが不明なため、認証時は仮の値）
    log_extra = {'job_info': 'AUTH'}

    # 1. Authorization ヘッダーチェック
    if not skip_auth:
        auth_header = request.headers.get('Authorization', '')
        is_auth_valid = auth_header.startswith('Bearer ')

        if not is_auth_valid:
            app.logger.error(f"REQ: {request.method} {request.path} | ERROR: Invalid Authorization Header.", extra=log_extra)
            return jsonify({"message": "Invalid headers or authentication failed.", "errorCode": "INVALID_SESSION_ID"}), 401
    
    # 2. Content-Type ヘッダーチェック
    content_type = request.headers.get('Content-Type', '')
    is_ct_valid = True
    if expected_content_type_prefix:
        is_ct_valid = content_type.lower().startswith(expected_content_type_prefix)
    
    if not is_ct_valid:
        app.logger.error(f"REQ: {request.method} {request.path} | ERROR: Invalid Content-Type. Expected: {expected_content_type_prefix}", extra=log_extra)
        # Content-Typeが不正な場合は415を返すのが一般的
        return jsonify({"message": f"Content-Type must be {expected_content_type_prefix}.", "errorCode": "UNSUPPORTED_MEDIA_TYPE"}), 415

    return None # 認証成功

# --- ヘルパー関数: Job ID生成 ---
def generate_job_id(interface_id):
    # jobIdのフォーマット: IF-XXXXXX + 750GC00000 + UUID(8文字) + ZAQ
    # ただし、IDにはハイフンを含めない仕様が多いので、ハイフンを除去
    prefix = interface_id.replace('-', '') 
    
    # UUIDをベースにしたランダム部分
    random_part = str(uuid.uuid4())[:8].upper()
    return f"{prefix}750GC00000{random_part}ZAQ"


#====================================================
# 1. POST: ジョブ作成 /jobs/ingest
#====================================================
@app.route(BASE_PATH, methods=['POST'])
def create_job():
    auth_check = check_auth_and_log(expected_content_type_prefix='application/json')
    if auth_check: return auth_check
    
    log_extra = {'job_info': 'CREATE'} # 仮のログ情報

    try:
        req_json = request.get_json(force=True)
    except:
        app.logger.error(f"REQ: POST {request.path} | ERROR: Invalid JSON format.", extra=log_extra)
        return jsonify({"message": "Invalid JSON format."}), 400
        
    object_name = req_json.get('object', 'Default__c')
    
    # --- object名に基づきインターフェース情報を取得 ---
    if object_name not in INTERFACE_MAPPING:
        app.logger.error(f"REQ: POST {request.path} | ERROR: Invalid object name: {object_name}", extra=log_extra)
        return jsonify({"message": f"Invalid object: {object_name}.", "errorCode": "INVALID_OBJECT"}), 400
        
    interface = INTERFACE_MAPPING[object_name]
    new_job_id = generate_job_id(interface['id'])
    now_utc = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    
    # --- ジョブ情報をJOB_STOREに保存 ---
    job_data = {
        "id": new_job_id,
        "object": object_name,
        "interface_id": interface['id'],
        "interface_name": interface['name'],
        "state": "Open",
        "sim_get_count": 0, # ポーリングシミュレーション用
        "externalIdFieldName": req_json.get('externalIdFieldName', 'ContractExternalId__c'),
    }
    JOB_STORE[new_job_id] = job_data
    
    log_info = f"{interface['id']}:{interface['name']}"
    app.logger.info(
        f"REQ: POST {request.path} | Job ID: {new_job_id} | Object: {object_name} | JSON Body: {req_json}", 
        extra={'job_info': log_info}
    )

    # --- レスポンス構築 ---
    response_body = {
        "id": new_job_id, 
        "operation": req_json.get('operation', 'upsert'), 
        "object": object_name,
        "createdByld": "005GC00000KhouiYAA", 
        "createdDate": now_utc, 
        "systemModstamp": now_utc,
        "state": "Open", 
        "externalIdFieldName": job_data["externalIdFieldName"],
        "concurrencyMode": "Parallel", 
        "contentType": req_json.get('contentType', 'CSV'),
        "apiVersion": 62.0, 
        "contentUrl": f"{BASE_PATH}/{new_job_id}/batches", 
        "lineEnding": req_json.get('lineEnding', 'CRLF'), 
        "columnDelimiter": "COMMA"
    }
    return jsonify(response_body), 200

#====================================================
# 2. PUT: CSV一括アップロード /jobs/ingest/{id}/batches
#====================================================
@app.route(BASE_PATH + '/<jobId>/batches', methods=['PUT'])
def handle_csv_batch(jobId):
    # 認証チェック (Content-Type: text/csvを期待)
    auth_check = check_auth_and_log(expected_content_type_prefix='text/csv')
    if auth_check: return auth_check
    
    if jobId not in JOB_STORE:
        log_extra = {'job_info': 'NOT_FOUND'}
        app.logger.error(f"RES: 404 NOT FOUND | Job ID: {jobId} ID not found.", extra=log_extra)
        return jsonify({"message": "The requested resource does not exist", "errorCode": "NOT_FOUND"}), 404

    job_data = JOB_STORE[jobId]
    job_info = f"{job_data['interface_id']}:{job_data['interface_name']}"
    log_extra = {'job_info': job_info}

    csv_data = request.data.decode('utf-8')
    csv_lines = csv_data.split('\n')
    preview = '\\n'.join(csv_lines[:3]) 
    
    app.logger.info(
        f"REQ: PUT {request.path} | Job ID: {jobId} | Object: {job_data['object']} | Data Size: {len(csv_data)} bytes", 
        extra=log_extra
    )
    app.logger.debug(f"CSV Preview (first 3 lines): {preview}", extra=log_extra)
    
    # 正常応答
    return Response(status=201)

#====================================================
# 3. PATCH: ステータス更新 /jobs/ingest/{id}
#====================================================
@app.route(BASE_PATH + '/<jobId>', methods=['PATCH'])
def update_job_state(jobId):
    # 認証チェック (Content-Type: application/jsonを期待)
    auth_check = check_auth_and_log(expected_content_type_prefix='application/json')
    if auth_check: return auth_check
    
    if jobId not in JOB_STORE:
        log_extra = {'job_info': 'NOT_FOUND'}
        app.logger.error(f"RES: 404 NOT FOUND | Job ID: {jobId} ID not found.", extra=log_extra)
        return jsonify({"message": "The requested resource does not exist", "errorCode": "NOT_FOUND"}), 404

    job_data = JOB_STORE[jobId]
    job_info = f"{job_data['interface_id']}:{job_data['interface_name']}"
    log_extra = {'job_info': job_info}

    try:
        request_json = request.get_json(force=True)
    except:
        app.logger.error(f"REQ: PATCH {request.path} | ERROR: Invalid JSON format.", extra=log_extra)
        return jsonify({"message": "Invalid JSON."}), 400

    
    if request_json.get('state') != 'UploadComplete':
        app.logger.error(f"REQ: PATCH {request.path} | Invalid state requested: {request_json.get('state')}", extra=log_extra)
        return jsonify({"message": "Invalid state.", "errorCode": "INVALID_STATE_VALUE"}), 400

    # 状態を更新
    job_data['state'] = 'UploadComplete'
    JOB_STORE[jobId] = job_data
    
    app.logger.info(
        f"REQ: PATCH {request.path} | Job ID: {jobId} | State updated to: UploadComplete | JSON Body: {request_json}", 
        extra=log_extra
    )

    # --- 正常応答 ---
    now_utc = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    response_body = {
        "id": jobId, 
        "operation": "upsert", 
        "object": job_data["object"],
        "createdByld": "005GC00000KhouiYAA", 
        "createdDate": "2024-11-14T09:38:00.000+0000",
        "systemModstamp": now_utc, 
        "state": job_data['state'], 
        "externalIdFieldName": job_data["externalIdFieldName"], 
        "concurrencyMode": "Parallel",
        "contentType": "CSV", 
        "apiVersion": 62.0
    }
    return jsonify(response_body), 200

#====================================================
# 4. GET: ジョブ詳細情報取得 /jobs/ingest/{id}
#====================================================
@app.route(BASE_PATH + '/<jobId>', methods=['GET'])
def get_job_details(jobId):
    # 認証チェック
    auth_check = check_auth_and_log()
    if auth_check: return auth_check
    
    if jobId not in JOB_STORE:
        log_extra = {'job_info': 'NOT_FOUND'}
        app.logger.error(f"RES: 404 NOT FOUND | Job ID: {jobId} ID not found.", extra=log_extra)
        return jsonify({"message": "The requested resource does not exist", "errorCode": "NOT_FOUND"}), 404
    
    job_data = JOB_STORE[jobId]
    job_info = f"{job_data['interface_id']}:{job_data['interface_name']}"
    log_extra = {'job_info': job_info}

    
    # ポーリング回数をインクリメント
    job_data['sim_get_count'] += 1
    
    # 状態シミュレーション: Open -> UploadComplete -> InProgress -> JobComplete
    current_state = job_data['state']
    
    if current_state == "UploadComplete":
        job_data['state'] = "InProgress"
        
    elif current_state == "InProgress" and job_data['sim_get_count'] >= MAX_GET_COUNT:
        job_data['state'] = "JobComplete"
        
    JOB_STORE[jobId] = job_data
        
    app.logger.info(
        f"REQ: GET {request.path} | Job ID: {jobId} | State Check | New State: {job_data['state']} (Poll Count: {job_data['sim_get_count']})",
        extra=log_extra
    )

    now_utc = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    
    # JobComplete 時の完了情報
    if job_data['state'] == 'JobComplete':
        processed = 2
        failed = 0
        total_time = 126
    else:
        processed = 0
        failed = 0
        total_time = 0
        
    base_response = {
        "id": jobId, 
        "operation": "upsert", 
        "object": job_data["object"],
        "createdByld": "005GC00000KhouiYAA", 
        "createdDate": "2024-11-14T09:39:09.000+0000",
        "externalIdFieldName": job_data["externalIdFieldName"], 
        "concurrencyMode": "Parallel",
        "state": job_data['state'], 
        "systemModstamp": now_utc, 
        "contentType": "CSV", 
        "apiVersion": 62.0, 
        "jobType": "V2Ingest", 
        "lineEnding": "CRLF", 
        "columnDelimiter": "COMMA", 
        "numberRecordsProcessed": processed, # 処理完了時に 2 を返す
        "numberRecordsFailed": failed,
        "retries": 0, 
        "totalProcessingTime": total_time,
        "apiActiveProcessingTime": 0, 
        "apexProcessingTime": 0, 
        "isPKChunkingSupported": False
    }
    return jsonify(base_response), 200

#====================================================
# 5. GET: 成功レコードリスト取得 /successfulResults
#====================================================
@app.route(BASE_PATH + '/<jobId>/successfulResults', methods=['GET'])
def get_successful_results(jobId):
    # 認証チェック
    auth_check = check_auth_and_log()
    if auth_check: return auth_check
    
    if jobId not in JOB_STORE:
        log_extra = {'job_info': 'NOT_FOUND'}
        app.logger.error(f"RES: 404 NOT FOUND | Job ID: {jobId} ID not found.", extra=log_extra)
        return jsonify({"message": "The requested resource does not exist", "errorCode": "NOT_FOUND"}), 404
        
    job_data = JOB_STORE[jobId]
    job_info = f"{job_data['interface_id']}:{job_data['interface_name']}"
    log_extra = {'job_info': job_info}

    app.logger.info(f"REQ: GET {request.path} | Job ID: {jobId}", extra=log_extra)

    # --- objectの値に基づいてCSVを切り替え (外部ファイルからロードしたデータを使用) ---
    object_name = job_data["object"]
    csv_data = LOADED_CSV_DATA["success"].get(object_name, "")
    
    if not csv_data:
        app.logger.error(f"CSV Data Missing: Could not load successful CSV data for object: {object_name}", extra=log_extra)
        return jsonify({"message": "CSV Data not found on server.", "errorCode": "INTERNAL_SERVER_ERROR"}), 500

    response = Response(csv_data, mimetype='text/csv')
    response.status_code = 200
    return response

#====================================================
# 6. GET: 失敗レコードリスト取得 /failedResults
#====================================================
@app.route(BASE_PATH + '/<jobId>/failedResults', methods=['GET'])
def get_failed_results(jobId):
    # 認証チェック
    auth_check = check_auth_and_log()
    if auth_check: return auth_check
    
    if jobId not in JOB_STORE:
        log_extra = {'job_info': 'NOT_FOUND'}
        app.logger.error(f"RES: 404 NOT FOUND | Job ID: {jobId} ID not found.", extra=log_extra)
        return jsonify({"message": "The requested resource does not exist", "errorCode": "NOT_FOUND"}), 404
        
    job_data = JOB_STORE[jobId]
    job_info = f"{job_data['interface_id']}:{job_data['interface_name']}"
    log_extra = {'job_info': job_info}
    
    app.logger.info(f"REQ: GET {request.path} | Job ID: {jobId}", extra=log_extra)

    # --- objectの値に基づいてCSVを切り替え (外部ファイルからロードしたデータを使用) ---
    object_name = job_data["object"]
    csv_data = LOADED_CSV_DATA["fail"].get(object_name, "")
    
    if not csv_data:
        app.logger.error(f"CSV Data Missing: Could not load failed CSV data for object: {object_name}", extra=log_extra)
        return jsonify({"message": "CSV Data not found on server.", "errorCode": "INTERNAL_SERVER_ERROR"}), 500
        
    response = Response(csv_data, mimetype='text/csv')
    response.status_code = 200
    return response

#====================================================
# 7. GET: 未処理レコードリスト取得 /unprocessedRecords/
#====================================================
@app.route(BASE_PATH + '/<jobId>/unprocessedRecords/', methods=['GET'])
def get_unprocessed_results(jobId):
    # 認証チェック
    auth_check = check_auth_and_log()
    if auth_check: return auth_check
    
    if jobId not in JOB_STORE:
        log_extra = {'job_info': 'NOT_FOUND'}
        app.logger.error(f"RES: 404 NOT FOUND | Job ID: {jobId} ID not found.", extra=log_extra)
        return jsonify({"message": "The requested resource does not exist", "errorCode": "NOT_FOUND"}), 404
    
    job_data = JOB_STORE[jobId]
    job_info = f"{job_data['interface_id']}:{job_data['interface_name']}"
    log_extra = {'job_info': job_info}
    
    app.logger.info(f"REQ: GET {request.path} | Job ID: {jobId}", extra=log_extra)

    # JobCompleteステータスの場合、未処理レコードは存在しないため404を返す
    if job_data["state"] == "JobComplete":
        app.logger.error(f"RES: 404 NOT FOUND | Job ID: {jobId} is JobComplete.", extra=log_extra)
        return jsonify({"message": "The requested resource does not exist", "errorCode": "NOT_FOUND"}), 404

    # --- objectの値に基づいてCSVを切り替え (外部ファイルからロードしたデータを使用) ---
    object_name = job_data["object"]
    csv_data = LOADED_CSV_DATA["unproc"].get(object_name, "")
    
    if not csv_data:
        app.logger.error(f"CSV Data Missing: Could not load unprocessed CSV data for object: {object_name}", extra=log_extra)
        return jsonify({"message": "CSV Data not found on server.", "errorCode": "INTERNAL_SERVER_ERROR"}), 500
    
    response = Response(csv_data, mimetype='text/csv')
    response.status_code = 200
    return response

# ====================================================
# 8. POST: Composite API (IF-360001: メール許諾情報 / IF-630001: 会員登録 / IF-630013: メール許諾詳細)
# ====================================================
@app.route(COMPOSITE_PATH, methods=['POST'])
def handle_composite_api():
    # 共通認証チェック (Content-Type: application/jsonを期待)
    auth_check = check_auth_and_log(expected_content_type_prefix='application/json')
    if auth_check: 
        return auth_check

    
    try:
        req_json = request.get_json(force=True)
    except:
        app.logger.error(f"REQ: POST {request.path} | ERROR: Invalid JSON format.", extra={'job_info': 'Composite:JSON_ERR'})
        return jsonify({"message": "Invalid JSON format."}), 400

    # 必須: compositeRequest配列と最初のサブ要求
    if not req_json.get('compositeRequest') or not isinstance(req_json['compositeRequest'], list) or not req_json['compositeRequest']:
        app.logger.error(f"REQ: POST {request.path} | ERROR: Missing or invalid compositeRequest array.", extra={'job_info': 'Composite:REQ_ERR'})
        return jsonify({"message": "Invalid composite request structure.", "errorCode": "INVALID_REQUEST"}), 400

    first_sub_request = req_json['compositeRequest'][0]
    method = first_sub_request.get('method', '').upper()
    sub_body = first_sub_request.get('body', {})
    
    # 2. X-API-Key の取得と正常/異常の判定
    api_key = request.headers.get('X-API-Key', '')
    is_success_key = (api_key == 'dummy_key_xyz')
    
    # 3. メソッドに基づくロジックの分岐
    
    if method == 'GET':
        # --- (A) IF-360001: メール許諾情報取得 (SELECT) ---
        log_info = "IF-360001:メール許諾情報(GET)"
        log_extra = {'job_info': log_info}
        
        app.logger.info(
            f"REQ: POST {request.path} | API Key: {api_key} | Case: {'SUCCESS' if is_success_key else 'ERROR'}", 
            extra=log_extra
        )

        if is_success_key:
            # 正常系レスポンス (内部 HttpStatusCode: 200)
            composite_response = {
                "compositeResponse": [
                    {
                        "body": {
                            "totalSize": 1,
                            "done": True,
                            "records": [
                                {
                                    "attributes": {
                                        "type": "Lead",
                                        "url": "/services/data/v62.0/sobjects/Lead/00QGC000001rXNgo2AG"
                                    },
                                    "EmailPermissionFlag__c": True
                                }
                            ]
                        },
                        "httpHeaders": {},
                        "httpStatusCode": 200, 
                        "referenceId": "GetLead"
                    }
                ]
            }
        else:
            # 異常系レスポンス (内部 HttpStatusCode: 400 - フィールド不正)
            composite_response = {
                "compositeResponse": [
                    {
                        "body": [
                            {
                                "message": "Field 'EmailPermissioFlag__c' is not supported in SOQL.",
                                "errorCode": "INVALID_FIELD"
                            }
                        ],
                        "httpHeaders": {},
                        "httpStatusCode": 400, 
                        "referenceId": "GetLead"
                    }
                ]
            }
        return jsonify(composite_response), 200
        
    elif method == 'PATCH':
        
        # --- PATCH内部のAPIを識別 ---
        if 'EmailPermissionFlag__c' in sub_body:
            # --- (B) IF-630013: メール許諾詳細情報 (PATCH) ---
            log_info = "IF-630013:メール許諾詳細(PATCH)"
            log_extra = {'job_info': log_info}

            app.logger.info(
                f"REQ: POST {request.path} | API Key: {api_key} | API: IF-630013 | Case: {'SUCCESS' if is_success_key else 'ERROR'}", 
                extra=log_extra
            )

            if is_success_key:
                # 正常系レスポンス (内部 HttpStatusCode: 200 - IF-630013の資料に基づく)
                composite_response = {
                    "compositeResponse": [
                        {
                            "body": {
                                "id": "00QGC000001rXj7Y2AC", 
                                "success": True,
                                "errors": [],
                                "created": False # 更新なので False
                            },
                            "httpHeaders": {
                                "Location": "/services/data/v60.0/sobjects/Lead/00QGC000001rXj7Y2AC"
                            },
                            "httpStatusCode": 200, # 資料の通り 200 に修正
                            "referenceId": "Lead"
                        }
                    ]
                }
            else:
                # 異常系レスポンス (内部 HttpStatusCode: 400 - ID不正など)
                composite_response = {
                    "compositeResponse": [
                        {
                            "body": [
                                {
                                    "message": "malformed id XXXXXXXXXXXXXXX.",
                                    "errorCode": "MALFORMED_ID"
                                }
                            ],
                            "httpHeaders": {},
                            "httpStatusCode": 400, 
                            "referenceId": "Lead"
                        }
                    ]
                }
            return jsonify(composite_response), 200

        else:
            # --- (C) IF-630001: 会員登録/更新 (PATCH) ---
            log_info = "IF-630001:会員登録(PATCH)"
            log_extra = {'job_info': log_info}

            app.logger.info(
                f"REQ: POST {request.path} | API Key: {api_key} | API: IF-630001 | Case: {'SUCCESS' if is_success_key else 'ERROR'}", 
                extra=log_extra
            )
            
            if is_success_key:
                # 正常系レスポンス (内部 HttpStatusCode: 201 - IF-630001の資料に基づく)
                composite_response = {
                    "compositeResponse": [
                        {
                            "body": {
                                "id": "00QGC000001rXNgo2AC", 
                                "success": True,
                                "errors": [],
                                "created": True
                            },
                            "httpHeaders": {
                                "Location": "/services/data/v62.0/sobjects/Lead/00QGC000001rXNgo2AC"
                            },
                            "httpStatusCode": 201, # 作成/更新成功時は 201
                            "referenceId": "Lead"
                        }
                    ]
                }
            else:
                # 異常系レスポンス (内部 HttpStatusCode: 400 - ID不正など)
                composite_response = {
                    "compositeResponse": [
                        {
                            "body": [
                                {
                                    "message": "malformed id XXXXXXXXXXXXXXX.",
                                    "errorCode": "MALFORMED_ID"
                                }
                            ],
                            "httpHeaders": {},
                            "httpStatusCode": 400, # サブ要求は異常
                            "referenceId": "Lead"
                        }
                    ]
                }
            return jsonify(composite_response), 200
        
    else:
        # 未対応メソッド
        log_info = f"Composite:UNKNOWN({method})"
        app.logger.warning(f"REQ: POST {request.path} | WARNING: Unsupported composite method: {method}", extra={'job_info': log_info})
        
        return jsonify({
            "message": f"Unsupported method in composite request: {method}", 
            "errorCode": "INVALID_METHOD"
        }), 400

# ====================================================
# 9. POST: OAuth Token /services/oauth2/token 
# ====================================================
@app.route(OAUTH_TOKEN_PATH, methods=['POST'])
def handle_oauth_token():
    # 認証チェック (Content-Type: application/x-www-form-urlencodedを期待, Authorizationヘッダーチェックはスキップ)
    auth_check = check_auth_and_log(
        expected_content_type_prefix='application/x-www-form-urlencoded', 
        skip_auth=True
    )
    if auth_check: 
        # Content-Typeが不正な場合は415が返る
        return auth_check

    log_info = "OAuth:Token"
    log_extra = {'job_info': log_info}
    
    # フォームデータの取得
    client_id = request.form.get('client_id')
    client_secret = request.form.get('client_secret')
    grant_type = request.form.get('grant_type')

    # シミュレーション用クライアントID
    SUCCESS_CLIENT_ID = 'stg'
    
    app.logger.info(
        f"REQ: POST {request.path} | grant_type: {grant_type} | client_id: {client_id}", 
        extra=log_extra
    )

    # 必須パラメータのチェック
    if not client_id or not client_secret or grant_type != 'client_credentials':
        app.logger.error(f"REQ: POST {request.path} | ERROR: Missing required parameters or invalid grant_type.", extra=log_extra)
        # 異常系レスポンス (HTTP 400)
        return jsonify({
            "error": "invalid_grant",
            "error_description": "missing or invalid credentials"
        }), 400
    
    # 正常系/異常系のシミュレーション
    if client_id == SUCCESS_CLIENT_ID:
        # 正常系レスポンス (HTTP 200)
        app.logger.info(f"RES: 200 OK | OAuth Token Success.", extra=log_extra)
        now_ts = str(int(datetime.datetime.now().timestamp()))

        response_body = {
            "access_token": "00DGC0000058Kad!AQpPQcxZw45oZ0Co8P4j0kMApekIMfABJvu_y7zpvb1nxbv0P5vRM_lCsvph_FIM4neQTVQXv3TH3WvsMuk4CpWu6v8xbg",
            "signature": "O+F5lk/JVr1igcveRHFEungRl9m3scP6dbYKwltuPL0=",
            "scope": "api",
            "instance_url": "https://dev-202407111759-dev-ed.develop.my.salesforce.com",
            "id": "https://login.salesforce.com/id/00DGC0000058KAD2AE/005GC00000KhBwYYAU",
            "token_type": "Bearer",
            "issued_at": now_ts
        }
        return jsonify(response_body), 200
        
    else:
        # 異常系レスポンス (HTTP 400)
        app.logger.error(f"RES: 400 Bad Request | Authentication Failure.", extra=log_extra)
        return jsonify({
            "error": "invalid_grant",
            "error_description": "authentication failure"
        }), 400


# --- サーバー起動ロジック ---
if __name__ == '__main__':
    # 起動ポートをコマンドライン引数から取得、ない場合はデフォルト8888
    port = 8888
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
        
    setup_logging()
    load_csv_data()
    
    app.logger.info(f"Flask API Stub starting on port {port}. Default port is 8888.", extra={'job_info': 'BOOT'})
    
    # Flaskサーバーの起動: debug=False で安定起動
    app.run(host='0.0.0.0', debug=False, port=port)
