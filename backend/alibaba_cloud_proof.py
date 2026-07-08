"""
Alibaba Cloud Services Integration Proof File

This script serves as the direct linkable proof for the "Proof of Alibaba Cloud Deployment" 
requirement in the Global AI Hackathon with Qwen Cloud submission.

It demonstrates how the Autopilot Agent System connects to Alibaba Cloud Object Storage Service (OSS)
using the official 'oss2' Python SDK to upload, archive, and persist critical incident remediation 
logs and agent memory backups.
"""

import os
import json
import logging
from datetime import datetime
import oss2

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AlibabaCloudOSSProof")

# Alibaba Cloud Credentials & Configuration
# In production, these environment variables are injected via ECS metadata, Function Compute, or Kubernetes Secret
OSS_ACCESS_KEY_ID = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
OSS_ACCESS_KEY_SECRET = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")
OSS_ENDPOINT = os.environ.get("ALIBABA_CLOUD_OSS_ENDPOINT", "oss-cn-singapore.aliyuncs.com")
OSS_BUCKET_NAME = os.environ.get("ALIBABA_CLOUD_OSS_BUCKET", "qwen-autopilot-incident-logs")

# Local Mock Archive Directory for local testing when cloud credentials are not supplied
LOCAL_ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "oss_mock_archive")
if not os.path.exists(LOCAL_ARCHIVE_DIR):
    os.makedirs(LOCAL_ARCHIVE_DIR)

def archive_incident_to_oss(incident_data: dict) -> dict:
    """
    Archives a completed incident remediation record to Alibaba Cloud OSS as a JSON file.
    Provides local fallback writing if credentials are not configured.
    """
    incident_id = incident_data.get("id", "unknown-id")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"incidents/{timestamp}_{incident_id}.json"
    json_payload = json.dumps(incident_data, indent=2, default=str)
    
    # Check if credentials are set
    if not OSS_ACCESS_KEY_ID or not OSS_ACCESS_KEY_SECRET:
        logger.warning(
            "ALIBABA_CLOUD_ACCESS_KEY_ID or SECRET is not set. "
            "Falling back to Local Mock OSS Archive to enable zero-config local testing."
        )
        
        # Save to local archive folder representing mock OSS
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
        # 1. Establish Auth credentials using Access Key ID and Access Key Secret
        auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
        
        # 2. Connect to the designated OSS Bucket
        bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)
        
        # 3. Upload the incident ticket payload as a JSON object
        logger.info(f"Uploading incident log '{file_name}' to Alibaba Cloud OSS bucket '{OSS_BUCKET_NAME}' at {OSS_ENDPOINT}...")
        result = bucket.put_object(file_name, json_payload)
        
        # 4. Confirm upload success by verifying HTTP status response
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
        # Log to local fallback folder on error
        fallback_file_path = os.path.join(LOCAL_ARCHIVE_DIR, f"fallback_{timestamp}_{incident_id}.json")
        with open(fallback_file_path, "w") as f:
            f.write(json_payload)
            
        return {
            "status": "oss_failed_fallback",
            "message": f"OSS upload failed, saved locally. Error: {str(e)}",
            "file_path": fallback_file_path,
            "oss_key": file_name
        }

def list_archived_logs() -> list:
    """
    Lists archived log files. Connects to Alibaba Cloud OSS if configured, 
    otherwise lists local archive items.
    """
    if not OSS_ACCESS_KEY_ID or not OSS_ACCESS_KEY_SECRET:
        # Return local files
        return [f for f in os.listdir(LOCAL_ARCHIVE_DIR) if f.endswith(".json")]
        
    try:
        auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
        bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)
        
        # List objects in bucket with 'incidents/' prefix
        objects = []
        for obj in oss2.ObjectIterator(bucket, prefix="incidents/"):
            objects.append({
                "key": obj.key,
                "size": obj.size,
                "last_modified": datetime.fromtimestamp(obj.last_modified).strftime("%Y-%m-%d %H:%M:%S")
            })
        return objects
    except Exception as e:
        logger.error(f"Failed to query Alibaba Cloud OSS bucket logs: {str(e)}")
        return []
