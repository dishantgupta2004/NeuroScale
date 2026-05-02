"""
S3 service.

Async wrapper around aioboto3 for S3 operations. We use it to:
  - Mirror uploaded documents to S3 (source of truth for re-indexing).
  - Generate presigned URLs so the frontend can download originals later.
  - Clean up on company offboarding.

Key namespacing
---------------
Every key is prefixed with the company_id:

    s3://{bucket}/companies/{company_id}/documents/{doc_id}/{filename}

This mirrors the FAISS folder layout (per-company isolation) and makes
"delete everything for company X" trivially `aws s3 rm --recursive`.

Auth
----
In dev: AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY env vars.
In prod (EC2): IAM Instance Profile — credentials are picked up
automatically, no env vars needed. aioboto3 handles both transparently.
"""
from __future__ import annotations

from typing import Any

import aioboto3
from botocore.exceptions import ClientError
from loguru import logger

from app.config import settings
from app.utils.exceptions import UpstreamError


def _build_doc_key(company_id: str, doc_id: str, filename: str) -> str:
    """Canonical S3 key for an uploaded document."""
    # Sanitize filename to keep keys clean. We don't decode it — S3 accepts
    # most chars, but we strip leading slashes and collapse whitespace.
    safe_name = filename.strip().replace("/", "_").replace("\\", "_") or "file"
    return f"companies/{company_id}/documents/{doc_id}/{safe_name}"


class S3Service:
    def __init__(self) -> None:
        # Session is cheap; clients are async context managers per-call.
        # In production with IAM instance profile, leave keys empty.
        self._session_kwargs: dict[str, Any] = {"region_name": settings.aws_region}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            self._session_kwargs.update(
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )
        self._bucket = settings.s3_bucket_docs

    def _session(self) -> aioboto3.Session:
        return aioboto3.Session(**self._session_kwargs)

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------
    async def upload_document(
        self,
        *,
        company_id: str,
        doc_id: str,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload bytes to S3. Returns the S3 key.

        We use put_object (not upload_fileobj) because:
          - Our files are bounded by max_upload_mb (25MB default).
          - put_object is single-shot async; upload_fileobj uses a thread pool.
          - For >100MB files we'd switch, but that's not the MVP.
        """
        key = _build_doc_key(company_id, doc_id, filename)
        try:
            async with self._session().client("s3") as s3:
                await s3.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=content,
                    ContentType=content_type,
                    # Tag with company_id for cost tracking + lifecycle rules.
                    Tagging=f"company_id={company_id}",
                )
            logger.info(f"S3 upload ok: s3://{self._bucket}/{key}")
            return key
        except ClientError as e:
            logger.error(f"S3 upload failed for {key}: {e}")
            raise UpstreamError(f"S3 upload failed: {e}") from e

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------
    async def download_document(self, key: str) -> bytes:
        try:
            async with self._session().client("s3") as s3:
                resp = await s3.get_object(Bucket=self._bucket, Key=key)
                # resp["Body"] is a StreamingBody; .read() returns bytes.
                return await resp["Body"].read()
        except ClientError as e:
            logger.error(f"S3 download failed for {key}: {e}")
            raise UpstreamError(f"S3 download failed: {e}") from e

    # ------------------------------------------------------------------
    # Presigned URL — for direct browser download without proxying through API
    # ------------------------------------------------------------------
    async def presigned_download_url(
        self, key: str, *, expires_in_seconds: int = 900
    ) -> str:
        """15-minute default. Useful for the Streamlit doc list view."""
        try:
            async with self._session().client("s3") as s3:
                url = await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self._bucket, "Key": key},
                    ExpiresIn=expires_in_seconds,
                )
            return url
        except ClientError as e:
            raise UpstreamError(f"Presign failed: {e}") from e

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    async def delete_document(self, key: str) -> None:
        try:
            async with self._session().client("s3") as s3:
                await s3.delete_object(Bucket=self._bucket, Key=key)
            logger.info(f"S3 delete ok: {key}")
        except ClientError as e:
            # Don't re-raise — DELETE in S3 is idempotent and we don't want
            # to block document row deletion if S3 has already lost the file.
            logger.warning(f"S3 delete failed for {key} (continuing): {e}")

    async def delete_company_prefix(self, company_id: str) -> int:
        """
        Wipe every object under companies/{company_id}/. Used for offboarding.

        Returns the number of objects deleted. S3 list_objects_v2 paginates
        in batches of 1000; we use the resource-level batch delete for
        efficiency.
        """
        prefix = f"companies/{company_id}/"
        deleted = 0
        try:
            async with self._session().resource("s3") as s3:
                bucket = await s3.Bucket(self._bucket)
                # objects.filter().delete() returns a list of API responses.
                async for obj in bucket.objects.filter(Prefix=prefix):
                    await obj.delete()
                    deleted += 1
            logger.info(f"S3 wiped prefix {prefix}: {deleted} objects")
            return deleted
        except ClientError as e:
            raise UpstreamError(f"S3 prefix delete failed: {e}") from e


s3_service = S3Service()