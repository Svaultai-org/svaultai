

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from typing import Optional

                                                                    
CLOSED_SET_REASONS = {
    "ok_engine_can_process":            "✓ Engine has work AND can drain it.",
    "empty_vault_no_files_to_scan":     "Vault has no uploaded files.",
    "all_files_terminal":               "Every file is analyzed / failed / unsupported.",
    "no_worker_registered":             "No drain function registered for any required stage.",
    "files_pending_but_no_queue_rows":  (
        "Files say pending but vault_analysis_jobs has zero "
        "rows — orphan state, the next scan will fix this."
    ),
    "queue_rows_for_unregistered_stage": (
        "Queue has jobs for a stage that has no drain function "
        "(missing optional dependency / unregistered worker)."
    ),
    "all_files_in_not_started":         (
        "Files were never enqueued; the next deep-answer step will "
        "enqueue them."
    ),
    "all_files_missing_extracted_text": (
        "Files are analyzed but extracted_text is empty — text "
        "extraction may have run but the writer skipped the row."
    ),
    "db_unavailable":                   "Could not connect to the database.",
    "unknown":                          "No matching closed-set reason — see counts above.",
}


def _hr(label: str) -> None:
    print()
    print(label)
    print("-" * max(8, len(label)))


def _print_kv(d: dict, indent: int = 2) -> None:
    if not d:
        print(" " * indent + "(empty)")
        return
    width = max(len(k) for k in d.keys())
    for k in sorted(d.keys()):
        print(" " * indent + f"{k.ljust(width)} : {d[k]}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose why a deep-answer scan isn't moving.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(__doc__ or ""),
    )
    parser.add_argument("--vault-id", required=True, help="Target vault UUID.")
    parser.add_argument(
        "--intent",
        default="search_files_for_credentials",
        help=(
            "Deep-answer intent (closed-set: search_files_for_credentials, "
            "search_files_about, list_by_tag, travel_readiness, "
            "related_files, vault_clusters). Defaults to the credential "
            "search intent."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit the diagnostic as a single JSON blob instead of formatted text.",
    )
    args = parser.parse_args(argv)

    vault_id = args.vault_id

                                                                        
    diagnostic: dict = {
        "vault_id": vault_id,
        "intent":   args.intent,
    }

                                     
    try:
        from vault_analysis import analysis_coverage_for_vault
        coverage = analysis_coverage_for_vault(vault_id) or {}
    except Exception as exc:
        coverage = {"_error": f"coverage_failed: {exc}"}
    diagnostic["coverage_by_analysis_status"] = coverage

                                                                    
    by_status, by_stage, by_stage_status, total_jobs = (
        _query_job_breakdown(vault_id)
    )
    diagnostic["jobs_by_status"]       = by_status
    diagnostic["jobs_by_stage"]        = by_stage
    diagnostic["jobs_by_stage_status"] = by_stage_status
    diagnostic["total_jobs"]           = total_jobs

                                                            
    extracted_counts = _query_extracted_text_counts(vault_id)
    diagnostic["extracted_text"] = extracted_counts

                                                                  
    diagnostic["registered_drain_functions"] = _registered_drain_functions()

                                        
    try:
        from vault_deep_answer import required_stages_for_intent
        required = list(required_stages_for_intent(args.intent))
    except Exception as exc:
        required = [f"_error: {exc}"]
    diagnostic["required_stages_for_intent"] = required

                                                                  
    diagnostic["recent_failed_jobs"] = _query_recent_failed_jobs(
        vault_id, limit=20,
    )

                 
    verdict = _verdict(
        coverage=coverage,
        jobs_by_status=by_status,
        jobs_by_stage=by_stage,
        registered=diagnostic["registered_drain_functions"],
        required=required,
    )
    diagnostic["verdict"]             = verdict
    diagnostic["verdict_explanation"] = CLOSED_SET_REASONS.get(
        verdict, CLOSED_SET_REASONS["unknown"],
    )

    if args.json:
        print(json.dumps(diagnostic, indent=2, default=str))
        return 0

                                                                        
    print(f"Deep-Answer scan diagnostic  vault={vault_id}  intent={args.intent}")
    print("=" * 70)

    _hr("Coverage (uploaded_files.analysis_status)")
    _print_kv({
        k: v for k, v in coverage.items() if not k.startswith("_")
    })

    _hr("vault_analysis_jobs by status")
    _print_kv(by_status)

    _hr("vault_analysis_jobs by stage")
    _print_kv(by_stage)

    _hr("vault_analysis_jobs by (stage, status)")
    if not by_stage_status:
        print("  (empty)")
    else:
        for stage in sorted(by_stage_status.keys()):
            print(f"  {stage}:")
            for status, n in sorted(by_stage_status[stage].items()):
                print(f"      {status.ljust(12)} : {n}")

    _hr("Extracted-text presence (counts only — never content)")
    _print_kv(extracted_counts)

    _hr("Required stages for this intent")
    print("  " + ", ".join(required))

    _hr("Registered drain functions")
    if not diagnostic["registered_drain_functions"]:
        print("  (NONE — engine cannot drain anything)")
    else:
        for r in diagnostic["registered_drain_functions"]:
            print(f"  {r}")
    missing = [
        s for s in required if s not in diagnostic["registered_drain_functions"]
    ]
    if missing:
        print(
            "  WARNING: required but unregistered → "
            + ", ".join(missing)
        )

    _hr("Last 20 failed jobs")
    if not diagnostic["recent_failed_jobs"]:
        print("  (none)")
    else:
        for j in diagnostic["recent_failed_jobs"]:
            print(
                f"  {j['completed_at'] or '-'}  stage={j['stage']:<20} "
                f"attempts={j['attempts']:>2}/{j['max_attempts']:<2} "
                f"err={(j.get('last_error') or '').strip()[:80]!r}"
            )

    _hr("Verdict (closed-set blocker code)")
    print(f"  {verdict}")
    print(f"  {diagnostic['verdict_explanation']}")
    return 0


def _get_conn():
    try:
        from main import get_db                
    except Exception:
        from vault_core import get_db                
    return get_db()


def _query_job_breakdown(vault_id: str):

    by_status: dict[str, int] = {}
    by_stage:  dict[str, int] = {}
    by_stage_status: dict[str, dict[str, int]] = {}
    total = 0
    try:
        conn = _get_conn()
    except Exception:
        return by_status, by_stage, by_stage_status, total
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT stage, status, COUNT(*)::INT "
            "FROM vault_analysis_jobs WHERE vault_id = %s "
            "GROUP BY stage, status",
            (vault_id,),
        )
        for stage, status, n in cur.fetchall() or []:
            stage = stage or "(null)"
            status = status or "(null)"
            n = int(n)
            total += n
            by_status[status] = by_status.get(status, 0) + n
            by_stage[stage]   = by_stage.get(stage, 0) + n
            by_stage_status.setdefault(stage, {})[status] = n
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return by_status, by_stage, by_stage_status, total


def _query_extracted_text_counts(vault_id: str) -> dict:


    out = {
        "files_with_extracted_text":       0,
        "pdfs_with_extracted_text":        0,
        "pdfs_total":                      0,
        "images_total":                    0,
        "scanned_pdf_candidates_for_ocr":  0,
    }
    try:
        conn = _get_conn()
    except Exception:
        return out
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM uploaded_files "
            "WHERE vault_id = %s AND extracted_text IS NOT NULL",
            (vault_id,),
        )
        out["files_with_extracted_text"] = int(cur.fetchone()[0] or 0)

        cur.execute(
            "SELECT COUNT(*) FROM uploaded_files "
            "WHERE vault_id = %s "
            "  AND (content_type ILIKE 'application/pdf%' "
            "       OR file_name ILIKE '%%.pdf')",
            (vault_id,),
        )
        out["pdfs_total"] = int(cur.fetchone()[0] or 0)

        cur.execute(
            "SELECT COUNT(*) FROM uploaded_files "
            "WHERE vault_id = %s "
            "  AND (content_type ILIKE 'application/pdf%' "
            "       OR file_name ILIKE '%%.pdf') "
            "  AND extracted_text IS NOT NULL",
            (vault_id,),
        )
        out["pdfs_with_extracted_text"] = int(cur.fetchone()[0] or 0)

        cur.execute(
            "SELECT COUNT(*) FROM uploaded_files "
            "WHERE vault_id = %s "
            "  AND content_type ILIKE 'image/%%'",
            (vault_id,),
        )
        out["images_total"] = int(cur.fetchone()[0] or 0)

                                                                 
        out["scanned_pdf_candidates_for_ocr"] = (
            out["pdfs_total"] - out["pdfs_with_extracted_text"]
        )
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def _query_recent_failed_jobs(vault_id: str, *, limit: int) -> list:
    out: list[dict] = []
    try:
        conn = _get_conn()
    except Exception:
        return out
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT job_id, stage, attempts, max_attempts, "
            "       last_error, completed_at "
            "FROM vault_analysis_jobs "
            "WHERE vault_id = %s AND status = 'failed' "
            "ORDER BY completed_at DESC NULLS LAST LIMIT %s",
            (vault_id, int(limit)),
        )
        for job_id, stage, attempts, max_attempts, last_error, completed_at \
                in cur.fetchall() or []:
            out.append({
                "job_id":       str(job_id),
                "stage":        stage,
                "attempts":     int(attempts),
                "max_attempts": int(max_attempts),
                "last_error":   last_error,
                "completed_at": completed_at.isoformat()
                                if completed_at else None,
            })
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def _registered_drain_functions() -> list[str]:


    out: list[str] = []
    try:
        from vault_analysis_worker import drain_text_extraction        
        out.append("text_extraction")
    except Exception:
        pass
    try:
        from vault_ocr_worker import drain_ocr        
        out.append("ocr")
    except Exception:
        pass
    try:
        from vault_archive_worker import drain_archive_indexing        
        out.append("archive_indexing")
    except Exception:
        pass
    try:
        from vault_audio_worker import drain_audio_transcription        
        out.append("audio_transcription")
    except Exception:
        pass
    try:
        from vault_understanding_worker import drain_file_understanding        
        out.append("file_understanding")
    except Exception:
        pass
    return out


def _verdict(
    *,
    coverage: dict,
    jobs_by_status: dict,
    jobs_by_stage: dict,
    registered: list,
    required: list,
) -> str:


    if "_error" in coverage:
        return "db_unavailable"
    total = int(coverage.get("total") or 0)
    analyzed = int(coverage.get("analyzed") or 0)
    pending  = int(coverage.get("pending") or 0)
    processing = int(coverage.get("processing") or 0)
    not_started = int(coverage.get("not_started") or 0)
    failed_n = int(coverage.get("failed") or 0)
    unsupported = int(coverage.get("unsupported") or 0)
    skipped = int(coverage.get("skipped") or 0)
    pending_jobs = int(jobs_by_status.get("pending") or 0)
    processing_jobs = int(jobs_by_status.get("processing") or 0)

    if total == 0:
        return "empty_vault_no_files_to_scan"

    registered_for_required = [s for s in required if s in registered]
    if not registered_for_required:
        return "no_worker_registered"

                             
    if (analyzed + failed_n + unsupported + skipped) >= total \
            and (pending + processing + not_started) == 0:
        if analyzed == 0:
                                                                
            return "all_files_terminal"
                         
        return "ok_engine_can_process"

                                                                   
    if pending > 0 and (pending_jobs + processing_jobs) == 0:
        return "files_pending_but_no_queue_rows"

                                                          
    queue_stages = {s for s, n in jobs_by_stage.items() if int(n or 0) > 0}
    if queue_stages and not (queue_stages & set(registered_for_required)):
        return "queue_rows_for_unregistered_stage"

                                                                     
    if not_started > 0 and pending == 0 and processing == 0:
        return "all_files_in_not_started"

                                                                
    return "ok_engine_can_process"


if __name__ == "__main__":
    sys.exit(main())
