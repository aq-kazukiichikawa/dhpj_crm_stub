#  Honda ONの売り方改革 外部連携APIのスタブ起動手順

このスタブサーバーは、PythonのFlaskフレームワークを使用し、標準でポート 8888 で動作します（ポート変更可）
保存のためにリポジトリに登録していますが、あくまでスタブなので、運用環境で自由に改変して使うことを前提としています。

## 1\. 前提条件

  * Python 3.8以上
  * flask ライブラリ
  * テストに必要なダミーCSVデータファイル

## 2\. フォルダ構成の準備

以下のフォルダ構成になっていることを確認してください。

```
任意のフォルダ/stub/
├── stub_api.py
└── data/
    ├── [各種CSVファイル 18個]
    └── ...
```

## 3\. 必要なライブラリのインストール

stub フォルダ（`任意のフォルダ/stub/`）に移動し、Flaskおよびその他必要な依存関係をインストールします。

```
# stubフォルダに移動
cd stub/

# 依存関係のインストール (venv環境内で行ってください)
# Mac/Linux (venvを activate してから実行)
source venv/bin/activate
pip install flask python-dotenv
deactivate

# Windows (venvを activate してから実行)
# PowerShellの場合:
# .\venv\Scripts\Activate
# Command Prompt (cmd.exe)の場合:
# .\venv\Scripts\activate.bat
#
# venvアクティベート後:
# pip install flask python-dotenv
# deactivate
```

## 4\. スタブサーバーの起動

`stub_api.py` を直接実行します。

  * Mac/Linux:

<!-- end list -->

```
python3 stub_api.py ポート番号(省略可能)
```

  * Windows:

<!-- end list -->

```
python stub_api.py ポート番号(省略可能)
```

サーバーが起動すると、以下のメッセージ（または類似のメッセージ）が表示されます。

```
* Running on http://127.0.0.1:8888
* Running on http://<ローカル環境のIPアドレス>:8888
```

この状態で、スタブサーバーはポート 8888 でリクエストを受け付け可能な状態です。

## 5\. ログファイルの確認

サーバーへのリクエスト詳細とジョブの状態遷移は、同じディレクトリ（`/mnt/ebs/tmp/test/stub/`）に生成される `stub_api.log` ファイルに出力されます。

```
# ログのリアルタイム確認 (Mac/Linux の場合)
tail -f stub_api.log
```

## 6\. 動作確認（cURLコマンド）

提供されている `test_commands_port_8888.sh` スクリプトに記載したコマンド群を使用して、APIフロー全体をテストできます。実行前に、スクリプト内の {YOUR\_JOB\_ID} を POST で取得したIDに置き換える必要があります。

## 7\. STGサーバー上での利用手順

STGサーバー上では、以下の手順と設定でスタブサーバーを起動・確認します。

### 7.1. サーバーのパス

実行パスは以下の通りです。

```
パス: /mnt/ebs/tmp/test/stub/
```

### 7.2. スタブサーバーの起動（STG環境向け）

STGサーバーでは、環境ごとに推奨ポートが異なります。

  * **STG 環境別の推奨ポート:**
      * STG1: 8881
      * STG2: 8882
      * STG3: 8883

以下の手順で venv をアクティベートし、適切なポートを指定して起動してください。

```
# 実行パスへ移動
cd /mnt/ebs/tmp/test/stub/
# venv環境をアクティベート
source venv/bin/activate

# サーバー起動 (例: STG3のポート8883を指定)
python stub_api.py 8883
```

### 7.3. ログファイルの確認

ログファイルは起動パスと同じ場所に出力されます。

```
ログパス: /mnt/ebs/tmp/test/stub/stub_api.log

[xxx@stg-rhel9-ecbko-solb1 ~]$ ll /mnt/ebs/tmp/test/stub/
# ... (stub_api.log があることを確認)

# ログのリアルタイム確認 (例)
tail -f /mnt/ebs/tmp/test/stub/stub_api.log
```

### 7.4. 動作確認時の注意点
- EC-APIからスタブを利用する場合、同じSTGサーバーからのアクセスなので`http://localhost:8883`(ポート番号は環境依存)を指定してください。
- 自PCからcURLなどのクライアントからスタブにアクセスする際は、`localhost` ではなく、STGサーバーのアドレス `https://stg3-api-solb.dmap.jp/` を使用してください。
