import os
import sys

sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("src"))

from src.storage.firestore_sync import firestore_sync

firestore_sync.initialize()
db = firestore_sync.db
articles_col = db.collection("articles")

all_docs = list(articles_col.stream())

print(f"Total articles: {len(all_docs)}")

two_or_more_perspectives = []
single_perspectives = []

for doc in all_docs:
    d = doc.to_dict()
    perspectives = d.get("perspectives", [])
    is_single = d.get("isSinglePerspective", True)
    div = d.get("divergenceScore", 0)
    
    if len(perspectives) >= 2:
        two_or_more_perspectives.append((doc.id, d.get("title", ""), is_single, div, len(perspectives)))
    else:
        single_perspectives.append((doc.id, d.get("title", ""), is_single, div, len(perspectives)))

print(f"Articles with >= 2 perspectives: {len(two_or_more_perspectives)}")
print(f"Articles with 1 perspective: {len(single_perspectives)}")

print("\nListing all articles with >= 2 perspectives:")
for doc_id, t, is_single, div, p_count in two_or_more_perspectives:
    print(f"- [{doc_id}] (isSingle: {is_single}, div: {div}, p_len: {p_count}) {t}")
