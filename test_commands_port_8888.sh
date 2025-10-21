# ----------------------------------------------------
# 共通変数の設定 (ポート 8888 に変更)
# ----------------------------------------------------
# AUTH_HEADERS変数の使用は中止し、ヘッダーは直接指定する
BASE_URL='http://localhost:8888/services/data/v62.0/jobs/ingest'
AUTH_TOKEN='Bearer dummy_token_abc'
API_KEY='dummy_key_xyz'

# OAuth トークン用のシークレット情報
SUCCESS_CLIENT_ID='stg'
SUCCESS_CLIENT_SECRET='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
ERROR_CLIENT_ID='INVALID_CLIENT_ID'

# ----------------------------------------------------
# 1. POST: ジョブ作成 (DeliveryTemp__c) - Job ID取得
# ----------------------------------------------------
# 実行後、レスポンスの "id" の値 (例: IF630008750GC00000XXXXXXXZAQ) をコピーしてね！
echo "--- 1. POST: Job Creation (DeliveryTemp__c) ---"
curl -X POST "${BASE_URL}" \
    -H "Content-Type: application/json" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{"operation": "upsert", "object": "DeliveryTemp__c", "contentType": "CSV", "externalIdFieldName": "ContractExternalId__c", "lineEnding": "CRLF"}'

# ----------------------------------------------------
# 1b. POST: ジョブ作成 (VehicleDefinition) - 別の Job ID取得
# ----------------------------------------------------
echo "\n--- 1b. POST: Job Creation (VehicleDefinition) ---"
curl -X POST "${BASE_URL}" \
    -H "Content-Type: application/json" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{"operation": "insert", "object": "VehicleDefinition", "contentType": "CSV", "externalIdFieldName": "TCCode__c", "lineEnding": "CRLF"}'


# ----------------------------------------------------
# 2. PUT: CSVデータアップロード
# ----------------------------------------------------
# 【要編集】 {YOUR_JOB_ID} をステップ1で取得したIDに置き換えてください
echo "\n--- 2. PUT: CSV Batch Upload ---"
curl -X PUT "${BASE_URL}/{YOUR_JOB_ID}/batches" \
    -H "Content-Type: text/csv" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: ${API_KEY}" \
    --data-binary $'ContractExternalId__c,NameKanjiMember__c\nPL123456,山田太郎\nPL987654,佐藤花子'

# ----------------------------------------------------
# 3. PATCH: ステータスを 'UploadComplete' に更新
# ----------------------------------------------------
# 【要編集】 {YOUR_JOB_ID} をステップ1で取得したIDに置き換えてください
echo "\n--- 3. PATCH: Set State to UploadComplete ---"
curl -X PATCH "${BASE_URL}/{YOUR_JOB_ID}" \
    -H "Content-Type: application/json" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{"state": "UploadComplete"}'

# ----------------------------------------------------
# 4. GET: ジョブ詳細情報取得 (ポーリングシミュレーション)
# ----------------------------------------------------
# 【要編集】 {YOUR_JOB_ID} をステップ1で取得したIDに置き換え、3回実行して JobComplete になるか確認
echo "\n--- 4. GET: Job Details (Polling attempts 1/3, State: InProgress) ---"
curl -X GET "${BASE_URL}/{YOUR_JOB_ID}" \
    -H "Accept: application/json" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: ${API_KEY}"

echo "\n--- 4. GET: Job Details (Polling attempts 2/3, State: InProgress) ---"
curl -X GET "${BASE_URL}/{YOUR_JOB_ID}" \
    -H "Accept: application/json" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: ${API_KEY}"

echo "\n--- 4. GET: Job Details (Polling attempts 3/3, State: JobComplete) ---"
curl -X GET "${BASE_URL}/{YOUR_JOB_ID}" \
    -H "Accept: application/json" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: ${API_KEY}"


# ----------------------------------------------------
# 5. GET: 成功レコードリスト取得 (CSV)
# ----------------------------------------------------
# 【要編集】 {YOUR_JOB_ID} をステップ1で取得したIDに置き換えてください
echo "\n--- 5. GET: Successful Records (CSV for DeliveryTemp__c) ---"
curl -X GET "${BASE_URL}/{YOUR_JOB_ID}/successfulResults" \
    -H "Accept: text/csv" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: ${API_KEY}"

# ----------------------------------------------------
# 6. GET: 失敗レコードリスト取得 (CSV)
# ----------------------------------------------------
# 【要編集】 {YOUR_JOB_ID} をステップ1で取得したIDに置き換えてください
echo "\n--- 6. GET: Failed Records (CSV for DeliveryTemp__c) ---"
curl -X GET "${BASE_URL}/{YOUR_JOB_ID}/failedResults" \
    -H "Accept: text/csv" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: ${API_KEY}"

# ----------------------------------------------------
# 7. GET: 未処理レコードリスト取得 (CSV) - JobComplete なので 404 が期待される
# ----------------------------------------------------
# 【要編集】 {YOUR_JOB_ID} をステップ1で取得したIDに置き換えてください
echo "\n--- 7. GET: Unprocessed Records (Expected 404/NOT_FOUND) ---"
curl -X GET "${BASE_URL}/{YOUR_JOB_ID}/unprocessedRecords/" \
    -H "Accept: text/csv" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: ${API_KEY}"

# ----------------------------------------------------
# 8. POST: Composite API (メール許諾情報取得) - 正常系シミュレーション
# ----------------------------------------------------
# X-API-Key: dummy_key_xyz -> 内部ステータス 200 (成功) を期待
echo "\n--- 8. POST: Composite API (Email Permission - Success Case) ---"
curl -X POST "http://localhost:8888/services/data/v62.0/composite" \
    -H "Content-Type: application/json" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "allOrNone": false,
        "collateSubrequests": false,
        "compositeRequest": [
            {
                "method": "GET",
                "url": "/services/data/v62.0/query?q=SELECT+EmailPermissionFlag__c+FROM+LEAD+WHERE+AuthId__c=111111111111",
                "referenceId": "GetLead"
            }
        ]
    }'

# ----------------------------------------------------
# 9. POST: Composite API (メール許諾情報取得) - 異常系シミュレーション
# ----------------------------------------------------
# X-API-Key: error_key_abc -> 内部ステータス 400 (失敗) を期待
echo "\n--- 9. POST: Composite API (Email Permission - Error Case) ---"
curl -X POST "http://localhost:8888/services/data/v62.0/composite" \
    -H "Content-Type: application/json" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: error_key_abc" \
    -d '{
        "allOrNone": false,
        "collateSubrequests": false,
        "compositeRequest": [
            {
                "method": "GET",
                "url": "/services/data/v62.0/query?q=SELECT+EmailPermissionFlag__c+FROM+LEAD+WHERE+AuthId__c=999999999999",
                "referenceId": "GetLead"
            }
        ]
    }'

# ----------------------------------------------------
# 10. POST: Composite API (会員登録 PATCH) - 正常系シミュレーション
# ----------------------------------------------------
# X-API-Key: dummy_key_xyz -> 内部ステータス 201 (成功) を期待
echo "\n--- 10. POST: Composite API (Member Registration PATCH - Success Case) ---"
# ポート番号は適宜修正してください (例: 8989)
curl -X POST "http://localhost:8888/services/data/v62.0/composite" \
    -H "Content-Type: application/json" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "allOrNone": false,
        "collateSubrequests": false,
        "compositeRequest": [
            {
                "method": "PATCH",
                "url": "/services/data/v62.0/sobjects/Lead/AuthID__c/00DH777SSD8765465",
                "referenceId": "Lead",
                "body": {
                    "LastName__c": "佐藤",
                    "FirstName__c": "太郎",
                    "MemberRegistrationDateTime__c": "2021-9-29T12:52:07Z",
                    "Sex__c": "0"
                }
            }
        ]
    }'

# ----------------------------------------------------
# 11. POST: Composite API (会員登録 PATCH) - 異常系シミュレーション
# ----------------------------------------------------
# X-API-Key: error_key_abc -> 内部ステータス 400 (ID不正エラー) を期待
echo "\n--- 11. POST: Composite API (Member Registration PATCH - Error Case) ---"
# ポート番号は適宜修正してください (例: 8989)
curl -X POST "http://localhost:8888/services/data/v62.0/composite" \
    -H "Content-Type: application/json" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: error_key_abc" \
    -d '{
        "allOrNone": false,
        "collateSubrequests": false,
        "compositeRequest": [
            {
                "method": "PATCH",
                "url": "/services/data/v62.0/sobjects/Lead/AuthID__c/INVALIDID_D8765465",
                "referenceId": "Lead",
                "body": {
                    "LastName__c": "佐藤",
                    "FirstName__c": "太郎"
                }
            }
        ]
    }'

# ----------------------------------------------------
# 12. POST: Composite API (IF-630013: メール許諾詳細 PATCH) - 正常系シミュレーション
# ----------------------------------------------------
# X-API-Key: dummy_key_xyz -> 内部ステータス 200 (成功) を期待
echo "\n--- 12. POST: Composite API (IF-630013: Email Permission Detail PATCH - Success Case) ---"
# ポート番号は適宜修正してください (例: 8989)
curl -X POST "http://localhost:8888/services/data/v62.0/composite" \
    -H "Content-Type: application/json" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "allOrNone": false,
        "collateSubrequests": false,
        "compositeRequest": [
            {
                "method": "PATCH",
                "url": "/services/data/v62.0/sobjects/Lead/AuthID__c/123456789000",
                "referenceId": "Lead",
                "body": {
                    "EmailPermissionFlag__c": true,
                    "EmailPermissionOutputDate__c": "2024-08-01",
                    "ConnectedSystem__c": "HONDAON"
                }
            }
        ]
    }'

# ----------------------------------------------------
# 13. POST: Composite API (IF-630013: メール許諾詳細 PATCH) - 異常系シミュレーション
# ----------------------------------------------------
# X-API-Key: error_key_abc -> 内部ステータス 400 (ID不正エラー) を期待
echo "\n--- 13. POST: Composite API (IF-630013: Email Permission Detail PATCH - Error Case) ---"
# ポート番号は適宜修正してください (例: 8989)
curl -X POST "http://localhost:8888/services/data/v62.0/composite" \
    -H "Content-Type: application/json" \
    -H "Authorization: ${AUTH_TOKEN}" \
    -H "X-API-Key: error_key_abc" \
    -d '{
        "allOrNone": false,
        "collateSubrequests": false,
        "compositeRequest": [
            {
                "method": "PATCH",
                "url": "/services/data/v62.0/sobjects/Lead/AuthID__c/INVALIDID_D8765465",
                "referenceId": "Lead",
                "body": {
                    "EmailPermissionFlag__c": false
                }
            }
        ]
    }'

# ----------------------------------------------------
# 14. POST: OAuth Token /services/oauth2/token - 正常系シミュレーション (新規)
# ----------------------------------------------------
echo "\n--- 14. POST: OAuth Token (Success Case) ---"
# Content-Type: application/x-www-form-urlencoded を使用
# ポート番号は適宜修正してください (例: 8989)
curl -X POST "http://localhost:8888/services/oauth2/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -H "X-API-Key: ${API_KEY}" \
    -d "grant_type=client_credentials&client_id=${SUCCESS_CLIENT_ID}&client_secret=${SUCCESS_CLIENT_SECRET}"

# ----------------------------------------------------
# 15. POST: OAuth Token /services/oauth2/token - 異常系シミュレーション (新規)
# ----------------------------------------------------
echo "\n--- 15. POST: OAuth Token (Error Case) ---"
# 不正な client_id を使用 -> 認証失敗エラーを期待
# ポート番号は適宜修正してください (例: 8989)
curl -X POST "http://localhost:8888/services/oauth2/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -H "X-API-Key: ${API_KEY}" \
    -d "grant_type=client_credentials&client_id=${ERROR_CLIENT_ID}&client_secret=dummy_secret"