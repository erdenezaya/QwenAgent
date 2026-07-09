import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("AlibabaCloudOSSPostmortem")

OSS_ACCESS_KEY_ID = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
OSS_ACCESS_KEY_SECRET = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")
OSS_ENDPOINT = os.environ.get("ALIBABA_CLOUD_OSS_ENDPOINT", "oss-cn-hangzhou.aliyuncs.com")
OSS_BUCKET_NAME = os.environ.get("ALIBABA_CLOUD_OSS_BUCKET", "qwen-autopilot-postmortems")

# Local Mock Archive Directory for local dev environments
LOCAL_ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "oss_mock_archive")
if not os.path.exists(LOCAL_ARCHIVE_DIR):
    os.makedirs(LOCAL_ARCHIVE_DIR)

async def upload_postmortem(session: dict) -> dict:
    """
    Archives a completed incident session trace payload to Alibaba Cloud OSS as a JSON file.
    Provides local fallback writing if credentials are not configured.
    """
    incident_id = session.get("alert", {}).get("id", "unknown-id")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"incidents/{timestamp}_{incident_id}.json"
    json_payload = json.dumps(session, indent=2, default=str)
    
    # Check if credentials are set
    if not OSS_ACCESS_KEY_ID or not OSS_ACCESS_KEY_SECRET:
        local_file_path = os.path.join(LOCAL_ARCHIVE_DIR, f"{timestamp}_{incident_id}.json")
        with open(local_file_path, "w") as f:
            f.write(json_payload)
            
        logger.info(f"Successfully archived incident record locally to: {local_file_path}")
        return {
            "status": "local_mock_success",
            "message": "Archived locally in mock OSS directory (credentials not supplied)",
            "file_path": local_file_path,
            "oss_key": file_name
        }

    try:
        import oss2
        auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
        bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)
        
        result = bucket.put_object(file_name, json_payload)
        
        if result.status == 200:
            logger.info(f"Successfully archived log to Alibaba Cloud OSS. HTTP Status: {result.status}")
            return {
                "status": "oss_success",
                "message": f"Archived to Alibaba Cloud OSS in bucket: {OSS_BUCKET_NAME}",
                "oss_key": file_name,
                "request_id": result.request_id
            }
        else:
            raise Exception(f"OSS returned non-200 status code: {result.status}")
            
    except Exception as e:
        logger.error(f"Alibaba Cloud OSS upload failed with error: {str(e)}")
        fallback_file_path = os.path.join(LOCAL_ARCHIVE_DIR, f"fallback_{timestamp}_{incident_id}.json")
        with open(fallback_file_path, "w") as f:
            f.write(json_payload)
            
        return {
            "status": "oss_failed_fallback",
            "message": f"OSS upload failed, saved locally. Error: {str(e)}",
            "file_path": fallback_file_path,
            "oss_key": file_name
        }
