import os
import sys
import json
import urllib.request
from google.oauth2 import service_account
from google.auth.transport.requests import Request

creds_path = 'firebase_service_account.json'
creds = service_account.Credentials.from_service_account_file(
    creds_path,
    scopes=['https://www.googleapis.com/auth/datastore', 'https://www.googleapis.com/auth/cloud-platform']
)

# Refresh token to get bearer token
creds.refresh(Request())
token = creds.token

url = 'https://firestore.googleapis.com/v1/projects/versus-69e13/databases/(default)/collectionGroups/articles/indexes'
index_body = {
    "queryScope": "COLLECTION",
    "fields": [
        {
            "fieldPath": "isSinglePerspective",
            "order": "ASCENDING"
        },
        {
            "fieldPath": "publishedAt",
            "order": "DESCENDING"
        }
    ]
}

req = urllib.request.Request(
    url,
    data=json.dumps(index_body).encode('utf-8'),
    headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }
)

try:
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        print(f"Index creation response: {res}")
except Exception as e:
    if hasattr(e, 'read'):
        print(f"Error creating index: {e.read().decode('utf-8')}")
    else:
        print(f"Error creating index: {e}")
