#!/bin/bash
# deploy-ui.sh
# Uploads cockpit static assets to OSS public site bucket

echo "=== Processing Cockpit UI Content Hashes ==="

# Run python script to automatically calculate content hashes and replace them in index.html
python -c "
import os, hashlib, re

def get_hash(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        h.update(f.read())
    return h.hexdigest()[:8]

if os.path.exists('src/static/app.js') and os.path.exists('src/static/style.css') and os.path.exists('src/static/index.html'):
    js_hash = get_hash('src/static/app.js')
    css_hash = get_hash('src/static/style.css')
    print(f'Computed Hashes - app.js: {js_hash}, style.css: {css_hash}')
    
    with open('src/static/index.html', 'r', encoding='utf-8') as f:
        content = f.read()
        
    content = re.sub(r'app\.js\?v=[a-zA-Z0-9.-]*', f'app.js?v={js_hash}', content)
    content = re.sub(r'style\.css\?v=[a-zA-Z0-9.-]*', f'style.css?v={css_hash}', content)
    
    with open('src/static/index.html', 'w', encoding='utf-8') as f:
        f.write(content)
    print('index.html updated successfully with content hashes.')
else:
    print('Static assets not found. Skipping hash injection.')
"

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
