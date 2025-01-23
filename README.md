# Word to Markdown 変換 Azure Function App

## 前提条件
- Azure サブスクリプション
- Azure CLI
- Docker
- pandoc
- Python 3.9.x
- Visual Studio Code
- Azure Functions Core Tools

## 環境セットアップ（Azure Cloud Shell）
```bash
# Python実行用の仮想環境の用意
python -m venv .venv
source .venv/bin/activate

# Pythonのバージョン確認（3.9.x）
python --version

# Azure Function Core Tools取得
wget https://github.com/Azure/azure-functions-core-tools/releases/download/4.0.6610/Azure.Functions.Cli.linux-x64.4.0.6610.zip

# Zipファイルの解凍
unzip -d azure-functions-cli Azure.Functions.Cli.linux-x64.4.0.6610.zip

# 実行権限付与
chmod +x ~/handson/azure-functions-cli/func
chmod +x ~/handson/azure-functions-cli/gozip
export PATH=$PATH:~/handson/azure-functions-cli

# Funcコマンド確認
func --version
```
## プロジェクトセットアップ

### プロジェクト作成　※code コマンドはVSCodeを起動するので修正後、Crtl+sで保存し、Ctrl+q で閉じる
```bash
mkdir WordToMarkdown && cd WordToMarkdown
```

### Dockerfile作成
```bash
code Dockerfile
```
```dockerfile
FROM mcr.microsoft.com/azure-functions/python:4-python3.9

ENV AzureFunctionsJobHost__Logging__Console__IsEnabled=true \
    AzureWebJobsScriptRoot=/home/site/wwwroot

COPY requirements.txt /

# Install pandoc latest version
RUN apt-get update && \
    apt-get install -y wget && \
    wget https://github.com/jgm/pandoc/releases/download/3.1.11.1/pandoc-3.1.11.1-1-amd64.deb && \
    dpkg -i pandoc-3.1.11.1-1-amd64.deb && \
    rm pandoc-3.1.11.1-1-amd64.deb && \
    apt-get clean && \
    pip install --no-cache-dir -r /requirements.txt

COPY . /home/site/wwwroot
```

### requirements.txt作成
```bash
code requirements.txt
```
```
azure-functions==1.21.3
azure-storage-blob==12.24.1
python-docx==1.1.2
pandoc==2.4
packaging==23.2
resolvelib==0.8.1
wheel==0.42.0
```

### host.json作成
```bash
code host.json
```
```json
{
  "version": "2.0",
  "logging": {
    "applicationInsights": {
      "samplingSettings": {
        "isEnabled": true,
        "excludedTypes": "Request"
      }
    }
  },
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  }
}
```

### WordToMarkdownFunction作成
```bash
mkdir WordToMarkdownFunction
code WordToMarkdownFunction/function.json
```
```json
{
    "scriptFile": "__init__.py",
    "bindings": [
        {
            "authLevel": "anonymous",
            "type": "httpTrigger",
            "direction": "in",
            "name": "req",
            "methods": [
                "post"
            ]
        },
        {
            "type": "http",
            "direction": "out",
            "name": "$return"
        }
    ]
}
```
```bash
code WordToMarkdownFunction/__init__.py
```
```python
import logging
import azure.functions as func
import os
import subprocess
from datetime import datetime
from azure.storage.blob import BlobServiceClient
import tempfile
import shutil
import json
import urllib.parse

def main(req: func.HttpRequest) -> func.HttpResponse:
   logging.info('Python HTTP trigger function processed a request.')

   try:
       req_body = req.get_json()
       input_container = req_body.get('inputContainer')
       input_blob_path = urllib.parse.unquote(req_body.get('inputBlobPath'))
       output_container = req_body.get('outputContainer')
       
       if not input_container or not input_blob_path or not output_container:
           return func.HttpResponse(
               json.dumps({
                   "status": "error",
                   "message": "Please provide inputContainer, inputBlobPath and outputContainer in the request body"
               }),
               mimetype="application/json",
               status_code=400
           )

       connect_str = os.environ['AzureStorageConnectionString']
       blob_service_client = BlobServiceClient.from_connection_string(connect_str)

       input_container_client = blob_service_client.get_container_client(input_container)
       input_blob_client = input_container_client.get_blob_client(input_blob_path)

       temp_dir = tempfile.mkdtemp()
       media_dir = os.path.join(temp_dir, 'media')
       os.makedirs(media_dir, exist_ok=True)
       
       try:
           input_file = os.path.join(temp_dir, os.path.basename(input_blob_path))
           with open(input_file, 'wb') as file:
               blob_data = input_blob_client.download_blob()
               file.write(blob_data.readall())

           output_filename = os.path.splitext(os.path.basename(input_blob_path))[0] + '.md'
           output_file = os.path.join(temp_dir, output_filename)

           subprocess.run([
               'pandoc',
               '-s',
               input_file,
               '--wrap=none',
               f'--extract-media={media_dir}',
               '-t',
               'gfm',
               '-o',
               output_file
           ], check=True)

           output_container_client = blob_service_client.get_container_client(output_container)
           timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

           result = {
               "markdown": None,
               "images": []
           }

           with open(output_file, 'rb') as data:
               blob_name = f"{timestamp}/{output_filename}"
               blob_client = output_container_client.get_blob_client(blob_name)
               blob_client.upload_blob(data)
               result["markdown"] = {
                   "name": output_filename,
                   "path": blob_name,
                   "container": output_container,
                   "url": blob_client.url
               }

           if os.path.exists(media_dir):
               for root, dirs, files in os.walk(media_dir):
                   for file in files:
                       file_path = os.path.join(root, file)
                       blob_name = f"{timestamp}/media/{file}"
                       with open(file_path, 'rb') as data:
                           blob_client = output_container_client.get_blob_client(blob_name)
                           blob_client.upload_blob(data)
                           props = blob_client.get_blob_properties()
                           result["images"].append({
                               "name": file,
                               "path": blob_name,
                               "container": output_container,
                               "url": blob_client.url,
                               "contentType": props.content_settings.content_type,
                               "size": props.size
                           })

           return func.HttpResponse(
               json.dumps({
                   "status": "success",
                   "message": f"Successfully processed {input_blob_path}",
                   "timestamp": timestamp,
                   "files": result
               }),
               mimetype="application/json"
           )

       finally:
           shutil.rmtree(temp_dir)

   except Exception as e:
       logging.error(f"Error: {str(e)}")
       return func.HttpResponse(
           json.dumps({
               "status": "error",
               "message": str(e)
           }),
           mimetype="application/json",
           status_code=500
       )
```

### フォルダ構造の確認
```
WordToMarkdown/
├── README.md
├── Dockerfile
├── requirements.txt
├── host.json
├── local.settings.json
└── WordToMarkdownFunction/
    ├── __init__.py
    └── function.json
``` 

## Azureリソース作成
```bash
# 変数設定（自分の名前を小文字で設定）
NAME=<your-name>
myResourceGroup=<your-resource-group-name>
LOCATION=japaneast

# 既存のストレージアカウントを利用する場合は下記を設定。違うリソースグループにあるストレージアカウントを指定すると手順エラーになるため注意
ConnectionString=<your-storage-connection-string>

# ストレージアカウント作成 ※既存のストレージアカウントを利用する場合はスキップ
az storage account create --name mystorageaccount${NAME} \
                          --resource-group ${myResourceGroup} \
                          --location ${LOCATION} \
                          --sku Standard_LRS

# ストレージアカウントの接続文字列を取得 ※既存のストレージアカウントを利用する場合はスキップ
ConnectionString=$(az storage account show-connection-string \
--name mystorageaccount${NAME} \
--resource-group ${myResourceGroup} \
--query connectionString \
--output tsv)

# Container Registry作成
az acr create --name wordtomdacr${NAME} \
              --resource-group ${myResourceGroup} \
              --sku Basic \
              --admin-enabled true

# 管理者ユーザー名とパスワードを変数に格納
ACR_USERNAME=$(az acr credential show --name wordtomdacr${NAME} --query "username" --output tsv)
ACR_PASSWORD=$(az acr credential show --name wordtomdacr${NAME} --query "passwords[0].value" --output tsv)

# Container Apps環境作成
az containerapp env create \
  --name managed-environment-${NAME} \
  --resource-group ${myResourceGroup} \
  --location japaneast

# Function App作成
az functionapp create \
  --name wordtomarkdownapp-${NAME} \
  --resource-group ${myResourceGroup} \
  --storage-account mystorageaccount${NAME} \
  --environment managed-environment-${NAME}

# Blobストレージのコンテナ作成
az storage container create --name word-input \
  --connection-string "${ConnectionString}"

az storage container create --name md-output \
  --connection-string "${ConnectionString}"
```


## デプロイ
```bash
# イメージのビルドとプッシュ
az acr build --registry wordtomdacr${NAME} --image wordtomdapp:v1 .

# Function Appにコンテナを設定
az functionapp config container set --name wordtomarkdownapp-${NAME} \
  --resource-group ${myResourceGroup} \
  --image wordtomdacr${NAME}.azurecr.io/wordtomdapp:v1 \
  --registry-server wordtomdacr${NAME}.azurecr.io \
  --registry-username $ACR_USERNAME \
  --registry-password $ACR_PASSWORD

# アプリケーション設定の追加
az functionapp config appsettings set --name wordtomarkdownapp-${NAME} \
                                     --resource-group ${myResourceGroup} \
                                     --settings AzureStorageConnectionString=${ConnectionString}

# CORSにAzure Portalを追加
az functionapp cors add --name wordtomarkdownapp-${NAME} \
  --resource-group ${myResourceGroup} \
  --allowed-origins https://portal.azure.com
```


## 使用方法
1. Wordファイルを `word-input` コンテナにアップロード

2. Function App に下記JSONをPOSTリクエスト
```json
{
    "inputContainer": "word-input",
    "inputBlobPath": "SAMPLE_会議室予約システム機能設計書.docx",
    "outputContainer": "md-output"
}
```

3. 変換結果は以下の場所に保存
- Markdownファイル：`md-container/[実行日時]/[元ファイル名].md`
- 画像ファイル：`md-container/[実行日時]/media/[画像ファイル名]`

## レスポンス形式
```json
{
  "status": "success",
  "message": "Successfully processed example.docx",
  "timestamp": "20250123_123456",
  "files": {
    "markdown": {
      "name": "example.md",
      "path": "20250123_123456/example.md",
      "container": "md-container",
      "url": "https://..."
    },
    "images": [
      {
        "name": "image1.png",
        "path": "20250123_123456/media/image1.png",
        "container": "md-container",
        "url": "https://...",
        "contentType": "image/png",
        "size": 12345
      }
    ]
  }
}
```

## リソースの削除
```bash
# 変数設定（自分の名前を小文字で設定）
NAME=<your-name>

# Function Appの削除
az functionapp delete --name wordtomarkdownapp-${NAME} \
                    --resource-group ${myResourceGroup}

# Container Apps環境の削除
az containerapp env delete --name managed-environment-${NAME} \
                         --resource-group ${myResourceGroup} \
                         --yes

# Container Registryの削除
az acr delete --name wordtomdacr${NAME} \
             --resource-group ${myResourceGroup} \
             --yes
```