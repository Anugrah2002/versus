"""
Versus Dual-View Debate Quality Auditor & Coherence Engine.
Uses the local Qwen model to verify that multi-perspective stories in Firestore
genuinely address the same core news event and provide meaningful divergent viewpoints.

Automatically cleans up the database by:
1. Keeping verified, authentic debates.
2. Converting mismatched/one-sided debates to single-source Briefs.
3. Splitting disjointed multi-topic clusters into separate independent Briefs.
4. Deleting broken or hallucinated stubs.
"""

from typing import List, Dict, Any, Optional, Tuple
import os
import sys
import json
import re
import urllib.request
import urllib.error
import time
from datetime import datetime, timezone

from config.settings import settings
from src.storage.firestore_sync import firestore_sync
from src.utils.logger import logger


from src.synthesis.providers.llamacpp_provider import LlamaCppProvider
from src.synthesis.providers.fallback_provider import local_fallback_synthesizer


class DebateAuditAction:
    KEEP_DUAL = "KEEP_DUAL"
    CONVERT_TO_BRIEF = "CONVERT_TO_BRIEF"
    SPLIT_TO_BRIEFS = "SPLIT_TO_BRIEFS"
    DELETE = "DELETE"


class LocalQwenAuditor:
    def __init__(self, ollama_url: str = "http://localhost:11434", model_name: str = "qwen3.5:9b"):
        self.ollama_url = ollama_url
        self.model_name = model_name
        self._is_ollama_available = None
        self.llamacpp = LlamaCppProvider()

    def check_ollama(self) -> bool:
        if self._is_ollama_available is not None:
            return self._is_ollama_available
        try:
            req = urllib.request.Request(f"{self.ollama_url}/api/tags", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                for m in models:
                    if "qwen" in m.lower():
                        self.model_name = m
                        break
                self._is_ollama_available = True
                logger.info(f"Connected to local Ollama synthesizer. Using model: '{self.model_name}'")
                return True
        except Exception:
            self._is_ollama_available = False
            return False

    def evaluate_debate_coherence(self, title: str, summary: str, perspectives: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluates whether perspectives belong to the same core event and present genuine opposing angles.
        Returns evaluation dict with is_coherent, action, and reasoning.
        """
        if len(perspectives) < 2:
            return {
                "is_coherent": False,
                "action": DebateAuditAction.CONVERT_TO_BRIEF,
                "reason": "Only 1 perspective present in document.",
                "confidence": 1.0
            }

        p1 = perspectives[0]
        p2 = perspectives[1]
        p1_title = p1.get("stanceTitle", "")
        p1_sum = p1.get("summary", "")
        p2_title = p2.get("stanceTitle", "")
        p2_sum = p2.get("summary", "")

        # 1. Primary: Local Qwen via Ollama (same local Qwen engine)
        if self.check_ollama():
            qwen_res = self._call_qwen_ollama(title, summary, p1_title, p1_sum, p2_title, p2_sum)
            if qwen_res:
                return qwen_res

        # 2. Secondary: Local Qwen via Llama.cpp GGUF
        if self.llamacpp.is_available:
            qwen_gguf_res = self._call_qwen_llamacpp(title, summary, p1_title, p1_sum, p2_title, p2_sum)
            if qwen_gguf_res:
                return qwen_gguf_res

        # 3. Tertiary: Local Synthesizer Semantic & Entity Overlap Fallback
        return self._evaluate_semantic_coherence(title, p1_title, p1_sum, p2_title, p2_sum)

    def _call_qwen_ollama(self, title: str, summary: str, p1_t: str, p1_s: str, p2_t: str, p2_s: str) -> Optional[Dict[str, Any]]:
        prompt = f"""You are an elite editorial auditor for a news intelligence app.
Analyze whether the two perspectives below belong to the SAME specific news event and present genuine contrasting viewpoints, or if they are two totally separate stories mistakenly grouped together.

Overall Story Title: {title}
Main Summary: {summary}

Perspective 1:
Title: {p1_t}
Content: {p1_s}

Perspective 2:
Title: {p2_t}
Content: {p2_s}

Decide one action:
- "KEEP_DUAL": Both perspectives genuinely address the SAME core news story or controversy from different viewpoints.
- "SPLIT_TO_BRIEFS": Perspectives describe two completely DIFFERENT unrelated news events (e.g. one is about sports, another about space).
- "CONVERT_TO_BRIEF": Perspective 1 is valid, but Perspective 2 is redundant, off-topic, or too generic.
- "DELETE": Content is spam, corrupted, or nonsensical.

Respond ONLY with a JSON object:
{{
  "is_coherent": true/false,
  "action": "KEEP_DUAL" | "SPLIT_TO_BRIEFS" | "CONVERT_TO_BRIEF" | "DELETE",
  "confidence": 0.0 - 1.0,
  "reason": "Brief explanation of topic alignment or discrepancy"
}}
"""
        req_data = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1}
        }

        try:
            req = urllib.request.Request(
                f"{self.ollama_url}/api/generate",
                data=json.dumps(req_data).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                text = res.get("response", "").strip()
                # Extract JSON block
                json_match = re.search(r"\{.*\}", text, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                    return {
                        "is_coherent": bool(parsed.get("is_coherent", False)),
                        "action": parsed.get("action", DebateAuditAction.KEEP_DUAL),
                        "reason": parsed.get("reason", "Qwen audit judgment"),
                        "confidence": float(parsed.get("confidence", 0.9))
                    }
        except Exception as e:
            logger.debug(f"Ollama Qwen call failed, falling back: {e}")
        return None

    def _call_qwen_llamacpp(self, title: str, summary: str, p1_t: str, p1_s: str, p2_t: str, p2_s: str) -> Optional[Dict[str, Any]]:
        prompt = f"""You are an elite editorial auditor for a news intelligence app.
Analyze whether the two perspectives below belong to the SAME specific news event and present genuine contrasting viewpoints, or if they are two totally separate stories mistakenly grouped together.

Overall Story Title: {title}
Main Summary: {summary}

Perspective 1:
Title: {p1_t}
Content: {p1_s}

Perspective 2:
Title: {p2_t}
Content: {p2_s}

Decide one action:
- "KEEP_DUAL": Both perspectives genuinely address the SAME core news story or controversy from different viewpoints.
- "SPLIT_TO_BRIEFS": Perspectives describe two completely DIFFERENT unrelated news events.
- "CONVERT_TO_BRIEF": Perspective 1 is valid, but Perspective 2 is redundant, off-topic, or too generic.
- "DELETE": Content is spam, corrupted, or nonsensical.

Respond ONLY with a JSON object:
{{"is_coherent": true/false, "action": "KEEP_DUAL"|"SPLIT_TO_BRIEFS"|"CONVERT_TO_BRIEF"|"DELETE", "confidence": 0.9, "reason": "Brief reason"}}
"""
        try:
            if not self.llamacpp._init_llm():
                return None
            res = self.llamacpp._llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": "You are a precise editorial auditor. Respond only in strict JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=250
            )
            text = res["choices"][0]["message"]["content"].strip()
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
                return {
                    "is_coherent": bool(parsed.get("is_coherent", False)),
                    "action": parsed.get("action", DebateAuditAction.KEEP_DUAL),
                    "reason": parsed.get("reason", "Qwen GGUF audit judgment"),
                    "confidence": float(parsed.get("confidence", 0.9))
                }
        except Exception as e:
            logger.debug(f"Llama.cpp Qwen call failed, falling back: {e}")
        return None

    def _evaluate_semantic_coherence(self, title: str, p1_t: str, p1_s: str, p2_t: str, p2_s: str) -> Dict[str, Any]:
        """High-precision entity and lexical topic overlap evaluator."""
        def extract_tokens(text: str) -> set:
            words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
            stop_words = {
                "that", "this", "with", "from", "have", "were", "they", "will", "what", "when",
                "where", "which", "about", "their", "there", "would", "could", "should", "other",
                "after", "first", "state", "report", "news", "said", "says", "while", "also"
            }
            return set(w for w in words if w not in stop_words)

        tokens_title = extract_tokens(title)
        tokens_p1 = extract_tokens(f"{p1_t} {p1_s}")
        tokens_p2 = extract_tokens(f"{p2_t} {p2_s}")

        # Check keyword intersection between perspectives
        common_between_p1_p2 = tokens_p1.intersection(tokens_p2)
        p1_title_overlap = tokens_title.intersection(tokens_p1)
        p2_title_overlap = tokens_title.intersection(tokens_p2)

        # If Perspective 1 and Perspective 2 share meaningful entities or key concepts
        if len(common_between_p1_p2) >= 2 or (len(p1_title_overlap) >= 2 and len(p2_title_overlap) >= 2):
            return {
                "is_coherent": True,
                "action": DebateAuditAction.KEEP_DUAL,
                "reason": f"Shared topical entities detected: {list(common_between_p1_p2)[:4]}",
                "confidence": 0.92
            }

        # Check if the title has "vs" or "and" linking two distinct items
        if " vs " in title.lower() or " vs. " in title.lower():
            return {
                "is_coherent": False,
                "action": DebateAuditAction.SPLIT_TO_BRIEFS,
                "reason": "Title shows disjointed topic fusion without semantic entity overlap.",
                "confidence": 0.88
            }

        if len(p1_title_overlap) >= 2 and len(p2_title_overlap) < 1:
            return {
                "is_coherent": False,
                "action": DebateAuditAction.CONVERT_TO_BRIEF,
                "reason": "Perspective 1 matches story title, but Perspective 2 is disconnected.",
                "confidence": 0.85
            }

        return {
            "is_coherent": True,
            "action": DebateAuditAction.KEEP_DUAL,
            "reason": "Contextually acceptable debate structure.",
            "confidence": 0.80
        }


class FirestoreDebateAuditWorkflow:
    def __init__(self, auditor: Optional[LocalQwenAuditor] = None):
        self.auditor = auditor or LocalQwenAuditor()

    def run_audit(
        self,
        dry_run: bool = True,
        limit: int = 200,
        batch_size: int = 15,
        max_runtime_seconds: int = 800
    ) -> Dict[str, Any]:
        """
        Scans Firestore Dual View articles in batches, evaluates coherence with Qwen,
        and applies batch writes to Firestore while gracefully respecting time budgets.
        """
        if not firestore_sync.initialize():
            logger.error("Failed to connect to Firestore.")
            return {"error": "Firestore not available"}

        db = firestore_sync.db
        articles_col = db.collection("articles")

        start_time = time.time()
        logger.info("=" * 65)
        logger.info(f"🔎 Starting Qwen Dual-View Audit (Dry-Run: {dry_run}, Limit: {limit}, Batch Size: {batch_size})")
        logger.info("=" * 65)

        # 1. Eager Batch Read: Read all target docs into memory immediately to close gRPC stream
        try:
            logger.info("Fetching target dual-view documents from Firestore into memory...")
            docs_stream = articles_col.where("isSinglePerspective", "==", False).limit(limit).stream()
            all_docs = list(docs_stream)
            total_docs = len(all_docs)
            logger.info(f"Successfully loaded {total_docs} dual-view documents in memory.")
        except Exception as e:
            logger.error(f"Error fetching documents from Firestore: {e}")
            return {"error": str(e)}

        if not all_docs:
            logger.info("No dual-view documents found to audit.")
            return {"total_scanned": 0, "status": "completed"}

        stats = {
            "total_scanned": 0,
            "kept_dual": 0,
            "converted_to_brief": 0,
            "split_to_briefs": 0,
            "deleted": 0,
            "actions_log": []
        }

        # 2. Process documents in batches of `batch_size`
        num_batches = (total_docs + batch_size - 1) // batch_size
        logger.info(f"Processing {total_docs} documents across {num_batches} batches...")

        for batch_idx in range(num_batches):
            # Check time budget safety before starting the batch
            elapsed = time.time() - start_time
            if elapsed >= max_runtime_seconds:
                logger.warning(
                    f"⏱️ Time budget reached ({elapsed:.1f}s >= {max_runtime_seconds}s). "
                    f"Stopping gracefully after {stats['total_scanned']} documents."
                )
                break

            batch_docs = all_docs[batch_idx * batch_size : (batch_idx + 1) * batch_size]
            logger.info(f"\n--- 📦 Processing Batch {batch_idx + 1}/{num_batches} ({len(batch_docs)} articles) ---")

            firestore_batch = db.batch()
            has_pending_writes = False

            for doc in batch_docs:
                doc_id = doc.id
                stats["total_scanned"] += 1
                try:
                    d = doc.to_dict() or {}
                    title = d.get("title", "")
                    summary = d.get("summary", "")
                    perspectives = d.get("perspectives", [])

                    # Individual LLM evaluation with local Qwen
                    evaluation = self.auditor.evaluate_debate_coherence(title, summary, perspectives)
                    action = evaluation["action"]
                    reason = evaluation["reason"]

                    log_entry = {
                        "doc_id": doc_id,
                        "title": title[:55],
                        "action": action,
                        "reason": reason,
                        "confidence": evaluation.get("confidence", 0.0)
                    }
                    stats["actions_log"].append(log_entry)

                    if action == DebateAuditAction.KEEP_DUAL:
                        stats["kept_dual"] += 1
                        logger.info(f"✅ [KEEP DUAL] [{doc_id}] {title[:48]}... (Reason: {reason})")

                    elif action == DebateAuditAction.CONVERT_TO_BRIEF:
                        stats["converted_to_brief"] += 1
                        logger.warning(f"🔄 [CONVERT TO BRIEF] [{doc_id}] {title[:48]}... (Reason: {reason})")
                        if not dry_run:
                            firestore_batch.update(doc.reference, {
                                "isSinglePerspective": True,
                                "divergenceScore": 0,
                                "consensusScore": 100
                            })
                            has_pending_writes = True

                    elif action == DebateAuditAction.SPLIT_TO_BRIEFS:
                        stats["split_to_briefs"] += 1
                        logger.warning(f"✂️ [SPLIT TO BRIEFS] [{doc_id}] {title[:48]}... (Reason: {reason})")
                        if not dry_run:
                            # 1. Update primary doc in batch
                            firestore_batch.update(doc.reference, {
                                "isSinglePerspective": True,
                                "divergenceScore": 0,
                                "consensusScore": 100
                            })
                            # 2. Create second perspective as its own independent brief
                            if len(perspectives) >= 2:
                                p2 = perspectives[1]
                                p2_id = f"{doc_id}_split"
                                p2_ref = articles_col.document(p2_id)
                                firestore_batch.set(p2_ref, {
                                    "id": p2_id,
                                    "title": p2.get("stanceTitle", title),
                                    "summary": p2.get("summary", summary),
                                    "category": d.get("category", "General"),
                                    "publishedAt": d.get("publishedAt", datetime.now(timezone.utc).isoformat()),
                                    "divergenceScore": 0,
                                    "consensusScore": 100,
                                    "heroImageUrl": d.get("heroImageUrl", ""),
                                    "isSinglePerspective": True,
                                    "perspectives": [p2],
                                    "tags": d.get("tags", []),
                                    "likesCount": 0,
                                    "commentsCount": 0,
                                    "sharesCount": 0,
                                    "bookmarksCount": 0,
                                    "readTimeMinutes": 2
                                })
                            has_pending_writes = True

                    elif action == DebateAuditAction.DELETE:
                        stats["deleted"] += 1
                        logger.error(f"🗑️ [DELETE STUB] [{doc_id}] {title[:48]}... (Reason: {reason})")
                        if not dry_run:
                            firestore_batch.delete(doc.reference)
                            has_pending_writes = True

                except Exception as doc_err:
                    logger.error(f"Error evaluating doc {doc_id}: {doc_err}")
                    continue

            # 3. Single Atomic Batch Write Call to Firestore
            if not dry_run and has_pending_writes:
                try:
                    logger.info(f"💾 Committing Batch {batch_idx + 1} atomic updates to Firestore...")
                    firestore_batch.commit()
                    logger.info(f"✅ Batch {batch_idx + 1} committed successfully.")
                except Exception as commit_err:
                    logger.error(f"❌ Error committing batch {batch_idx + 1}: {commit_err}")

        total_time = time.time() - start_time
        logger.info("=" * 65)
        logger.info(f"📊 Qwen Dual-View Audit Summary (Completed in {total_time:.1f}s):")
        logger.info(f"  • Total Debates Scanned: {stats['total_scanned']}/{total_docs}")
        logger.info(f"  • Authentic Debates Kept: {stats['kept_dual']}")
        logger.info(f"  • Converted to Briefs: {stats['converted_to_brief']}")
        logger.info(f"  • Disjointed Topics Split: {stats['split_to_briefs']}")
        logger.info(f"  • Defective/Stubs Deleted: {stats['deleted']}")
        logger.info("=" * 65)

        return stats
