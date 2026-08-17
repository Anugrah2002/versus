import os
import sys
from collections import Counter

sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("src"))

from src.storage.firestore_sync import firestore_sync

if not firestore_sync.initialize():
    print("Failed to initialize Firestore.")
    sys.exit(1)

db = firestore_sync.db
articles_col = db.collection("articles")

print("Scanning Firestore articles...")

all_docs = list(articles_col.stream())
total_count = len(all_docs)
dual_count = 0
brief_count = 0
dual_with_2_perspectives = 0
brief_with_2_perspectives = 0
categories = Counter()

sample_duals = []
converted_candidates = []

for doc in all_docs:
    d = doc.to_dict()
    is_single = d.get("isSinglePerspective", True)
    perspectives = d.get("perspectives", [])
    title = d.get("title", "No Title")
    cat = d.get("category", "General")
    categories[cat] += 1
    
    if not is_single:
        dual_count += 1
        if len(perspectives) >= 2:
            dual_with_2_perspectives += 1
            if len(sample_duals) < 10:
                sample_duals.append((doc.id, title, [p.get("stanceTitle", "") for p in perspectives]))
    else:
        brief_count += 1
        if len(perspectives) >= 2:
            brief_with_2_perspectives += 1
            if len(converted_candidates) < 15:
                converted_candidates.append((doc.id, title, [p.get("stanceTitle", "") for p in perspectives]))

print(f"\n📊 FIRESTORE AUDIT STATS:")
print(f"Total articles in DB: {total_count}")
print(f"Dual Views (isSinglePerspective == False): {dual_count}")
print(f"Dual Views with >= 2 perspectives: {dual_with_2_perspectives}")
print(f"Briefs (isSinglePerspective == True): {brief_count}")
print(f"Briefs that have >= 2 perspectives stored: {brief_with_2_perspectives}")

print(f"\nCategories: {dict(categories)}")

print(f"\n🔍 Current Active Dual Views (Sample {len(sample_duals)}):")
for doc_id, t, stances in sample_duals:
    print(f"  [{doc_id}] {t}")
    print(f"     Stances: {stances}")

print(f"\n🔍 Briefs with >= 2 perspectives (Potentially converted by audit) (Sample {len(converted_candidates)}):")
for doc_id, t, stances in converted_candidates:
    print(f"  [{doc_id}] {t}")
    print(f"     Stances: {stances}")
