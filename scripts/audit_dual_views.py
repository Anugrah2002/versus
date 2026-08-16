"""
CLI entrypoint for running the isolated Qwen Dual-View Quality Audit Workflow.

Usage:
  python scripts/audit_dual_views.py --dry-run
  python scripts/audit_dual_views.py --apply --limit 250
"""

import sys
import os
import argparse

# Add project root and src to sys.path
sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("src"))

from src.audit.debate_auditor import FirestoreDebateAuditWorkflow, LocalQwenAuditor
from src.utils.logger import logger


def main():
    parser = argparse.ArgumentParser(description="Audit Firestore Dual Views using Local Qwen")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Preview actions without modifying Firestore")
    parser.add_argument("--apply", action="store_true", default=False, help="Commit updates/deletions directly to Firestore")
    parser.add_argument("--limit", type=int, default=250, help="Maximum number of dual view articles to audit")
    parser.add_argument("--batch-size", type=int, default=15, help="Number of documents to process per batch before committing to Firestore")
    parser.add_argument("--max-runtime", type=int, default=800, help="Maximum execution time budget in seconds before graceful exit")
    parser.add_argument("--ollama-url", type=str, default="http://localhost:11434", help="Local Ollama endpoint URL")

    args = parser.parse_args()

    # Default to dry-run unless --apply is explicitly specified
    is_dry_run = not args.apply

    logger.info("Initializing Local Qwen Debate Auditor...")
    auditor = LocalQwenAuditor(ollama_url=args.ollama_url)
    workflow = FirestoreDebateAuditWorkflow(auditor=auditor)

    stats = workflow.run_audit(
        dry_run=is_dry_run,
        limit=args.limit,
        batch_size=args.batch_size,
        max_runtime_seconds=args.max_runtime
    )

    if is_dry_run:
        print("\n[NOTE] Ran in DRY-RUN mode. No Firestore documents were modified.")
        print("To apply changes, run with: python scripts/audit_dual_views.py --apply\n")


if __name__ == "__main__":
    main()
