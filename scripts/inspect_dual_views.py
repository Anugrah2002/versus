import os
import sys
import json
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

# Stream all articles with isSinglePerspective == False
docs = articles_col.where('isSinglePerspective', '==', False).stream()
dual_articles = []

for doc in docs:
    d = doc.to_dict()
    doc_id = doc.id
    title = d.get('title', '')
    summary = d.get('summary', '')
    category = d.get('category', '')
    div = d.get('divergenceScore', 0)
    perspectives = d.get('perspectives', [])
    p_lens = [len(p.get('summary', '').split()) for p in perspectives]
    dual_articles.append({
        'id': doc_id,
        'title': title,
        'category': category,
        'divergence': div,
        'num_perspectives': len(perspectives),
        'perspective_word_counts': p_lens,
        'perspectives': perspectives,
    })

print(f"Total Firestore documents with isSinglePerspective == False: {len(dual_articles)}")

valid_duals = 0
invalid_duals = 0

for i, a in enumerate(dual_articles, 1):
    is_valid = a['num_perspectives'] >= 2 and all(p >= 25 for p in a['perspective_word_counts'])
    status = "VALID DUAL" if is_valid else "INVALID / DEFECTIVE"
    if is_valid:
        valid_duals += 1
    else:
        invalid_duals += 1
    print(f"{i}. [{status}] [{a['id']}] (p_count={a['num_perspectives']}, div={a['divergence']}%, words={a['perspective_word_counts']}): {a['title'][:60]}")
    if not is_valid:
        print(f"   REASON: num_perspectives={a['num_perspectives']}, word_counts={a['perspective_word_counts']}")

print(f"\n--- TOTALS ---")
print(f"Valid High-Quality Dual View debates: {valid_duals}")
print(f"Invalid / Defective Dual View documents: {invalid_duals}")
