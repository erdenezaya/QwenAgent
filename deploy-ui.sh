#!/bin/bash
# deploy-ui.sh
# Uploads cockpit static assets to OSS public site bucket

echo "=== Uploading Cockpit UI Static Assets ==="

# Reads the bucket name output from terraform
BUCKET_NAME=$(cd infra/terraform && terraform output -raw cockpit_ui_url | cut -d'/' -f3 | cut -d'.' -f1)

if [ -z "$BUCKET_NAME" ]; then
  echo "Error: Could not retrieve OSS bucket name. Did you run 'terraform apply'?"
  exit 1
fi

echo "Uploading files to OSS bucket: $BUCKET_NAME"

# Python helper fallback to perform upload if aliyun-ossutil is not installed
python -c "
import os, oss2
access_key = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID', '')
secret_key = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET', '')
endpoint = os.environ.get('ALIBABA_CLOUD_OSS_ENDPOINT', 'oss-cn-hangzhou.aliyuncs.com')
if not access_key:
    print('Error: ALIBABA_CLOUD_ACCESS_KEY_ID environment variable is missing.')
    exit(1)
auth = oss2.Auth(access_key, secret_key)
bucket = oss2.Bucket(auth, endpoint, '$BUCKET_NAME')
for root, dirs, files in os.walk('src/static'):
    for file in files:
        local_path = os.path.join(root, file)
        rel_path = os.path.relpath(local_path, 'src/static')
        print(f'Uploading {rel_path}...')
        bucket.put_object(rel_path.replace(chr(92), '/'), open(local_path, 'rb'))
"

echo "UI static deployment completed successfully!"
