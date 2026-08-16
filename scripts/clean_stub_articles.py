import sys
import os
from pathlib import Path

# Add project root and src to path
sys.path.insert(0, os.path.abspath('.'))
sys.path.insert(0, os.path.abspath('src'))

from storage.firestore_sync import firestore_sync

if not firestore_sync.initialize():
    print("Failed to initialize Firestore with service account.")
    sys.exit(1)

db = firestore_sync.db
articles_col = db.collection('articles')

# 1. Scan and delete stub articles with < 25 words
docs = articles_col.stream()
deleted_count = 0
retained_count = 0

for doc in docs:
    d = doc.to_dict()
    summary = d.get('summary', '')
    perspectives = d.get('perspectives', [])
    p_summaries = [p.get('summary', '') for p in perspectives]
    
    # Check if this is a stub article (less than 25 words)
    s_words = len(summary.split())
    p_min_words = min([len(ps.split()) for ps in p_summaries]) if p_summaries else s_words
    
    if s_words < 25 or p_min_words < 25:
        print(f"Deleting stub article [{doc.id}] ({s_words} words): {d.get('title', '')[:50]}", flush=True)
        doc.reference.delete()
        deleted_count += 1
    else:
        retained_count += 1

print(f"\n--- FIRESTORE CLEANUP SUMMARY ---", flush=True)
print(f"Deleted stub articles: {deleted_count}", flush=True)
print(f"Retained high-quality articles: {retained_count}", flush=True)
