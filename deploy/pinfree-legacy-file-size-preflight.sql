-- Count-only legacy file readiness check for the private PIN cutover.
-- Run with a SELECT-only role after confirming the deployed schema. The
-- output contains aggregate counts only: no vault IDs, filenames, content,
-- ciphertext, PINs, or record sizes are returned.
--
-- Current client stage defers a single legacy source above 8 MiB of encoded
-- ciphertext. The server export and retire paths reject one above 64 MiB.
-- Extra text/path fields above 64 KiB/4 KiB also need separate handling.
-- A nonzero result in those groups is a cutover blocker until a tested
-- streaming or other owner-verified path covers the exact records.
\set ON_ERROR_STOP on
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

WITH file_shapes AS (
    SELECT vault_id,
           storage_mode,
           upload_status,
           encrypted_file_data IS NOT NULL AS has_legacy_inline_bytes,
           length(encrypted_file_data)::bigint AS ciphertext_chars,
           octet_length(extracted_text)::bigint AS extra_text_bytes,
           octet_length(relative_path)::bigint AS extra_path_bytes
      FROM uploaded_files
)
SELECT
    count(*) AS file_rows_total,
    count(*) FILTER (
        WHERE storage_mode = 'inline' AND upload_status = 'complete'
          AND has_legacy_inline_bytes
    ) AS legacy_inline_complete,
    count(*) FILTER (
        WHERE storage_mode = 'inline' AND upload_status = 'complete'
          AND has_legacy_inline_bytes
          AND ciphertext_chars > 8 * 1024 * 1024
    ) AS legacy_inline_above_client_8m,
    count(DISTINCT vault_id) FILTER (
        WHERE storage_mode = 'inline' AND upload_status = 'complete'
          AND has_legacy_inline_bytes
          AND ciphertext_chars > 8 * 1024 * 1024
    ) AS vaults_with_legacy_inline_above_client_8m,
    count(*) FILTER (
        WHERE storage_mode = 'inline' AND upload_status = 'complete'
          AND has_legacy_inline_bytes
          AND ciphertext_chars > 64 * 1024 * 1024
    ) AS legacy_inline_above_server_64m,
    count(*) FILTER (
        WHERE storage_mode = 'inline' AND upload_status = 'complete'
          AND has_legacy_inline_bytes
          AND (extra_text_bytes IS NOT NULL OR extra_path_bytes IS NOT NULL)
    ) AS legacy_inline_with_extra_fields,
    count(*) FILTER (
        WHERE storage_mode = 'inline' AND upload_status = 'complete'
          AND has_legacy_inline_bytes
          AND extra_text_bytes > 64 * 1024
    ) AS legacy_inline_extra_text_above_64k,
    count(*) FILTER (
        WHERE storage_mode = 'inline' AND upload_status = 'complete'
          AND has_legacy_inline_bytes
          AND extra_path_bytes > 4096
    ) AS legacy_inline_extra_path_above_4k,
    count(*) FILTER (
        WHERE upload_status = 'pending'
    ) AS uploads_pending_any_mode,
    count(*) FILTER (
        WHERE storage_mode = 'chunked' AND upload_status = 'pending'
    ) AS chunked_uploads_pending,
    count(*) FILTER (
        WHERE storage_mode = 'chunked' AND upload_status = 'complete'
    ) AS chunked_uploads_complete,
    count(*) FILTER (
        WHERE storage_mode = 'chunked' AND upload_status = 'failed'
    ) AS chunked_uploads_failed,
    (SELECT count(*) FROM uploaded_file_chunks) AS legacy_chunk_rows_total
FROM file_shapes;

ROLLBACK;
