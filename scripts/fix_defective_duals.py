import os
import sys
from pathlib import Path

# Add project root and src to sys.path
sys.path.insert(0, os.path.abspath('.'))
sys.path.insert(0, os.path.abspath('src'))

from storage.firestore_sync import firestore_sync

if not firestore_sync.initialize():
    print("Failed to initialize Firestore.")
    sys.exit(1)

db = firestore_sync.db
articles_col = db.collection('articles')

# Stream all articles where isSinglePerspective == False
docs = articles_col.where('isSinglePerspective', '==', False).stream()
fixed_count = 0

for doc in docs:
    d = doc.to_dict()
    perspectives = d.get('perspectives', [])
    
    # If it has only 1 perspective or 0, it's not a Dual View! Fix it to isSinglePerspective = True
    if len(perspectives) <= 1:
        print(f"Fixing defective dual view [{doc.id}] ({len(perspectives)} perspectives): {d.get('title', '')[:50]}", flush=True)
        doc.reference.update({
            'isSinglePerspective': True,
            'divergenceScore': 0,
            'consensusScore': 100
        })
        fixed_count += 1

print(f"\n--- FIRESTORE DUAL VIEW FIX SUMMARY ---", flush=True)
print(f"Fixed {fixed_count} defective documents to isSinglePerspective=True", flush=True)
