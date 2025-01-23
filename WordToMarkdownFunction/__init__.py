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