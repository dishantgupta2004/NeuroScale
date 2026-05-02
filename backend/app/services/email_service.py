"""
Email service.

Two-step flow with explicit human approval:

    draft (or generate via agent) -> EmailLog row (pending_approval)
                                     │
                                     ▼ user clicks Approve in UI
                                  status=approved, then call SES
                                     │
                                     ▼
                                  status=sent (or send_failed)

The actual SES send is a placeholder here — Phase 6 wires the real boto3
client. We intentionally leave a clean seam (`_send_via_ses`) to fill in.
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import agent_graph
from app.config import settings
from app.db.tables import EmailLog
from app.models.email import (
    ApproveEmailRequest,
    DraftEmailRequest,
    EmailListResponse,
    EmailResponse,
)
from app.utils.exceptions import (
    ConflictError,
    NotFoundError,
    UpstreamError,
    ValidationError,
)


class EmailService:
    async def draft(
        self,
        db: AsyncSession,
        *,
        company_id: str,
        user_id: str,
        payload: DraftEmailRequest,
    ) -> EmailResponse:
        # Either explicit body OR a generation_task — not neither.
        if not payload.body and not payload.generation_task:
            raise ValidationError("Either `body` or `generation_task` must be provided")

        subject = payload.subject
        body = payload.body
        agent_run_id: str | None = None

        # If body is missing, run the agent graph to generate one.
        if body is None:
            assert payload.generation_task is not None
            final_state = await agent_graph.run(
                company_id=company_id,
                run_id="email-draft",   # ephemeral id; not persisted as agent_run here
                task=payload.generation_task,
                content_type="email",
                target_audience=None,
            )
            body = final_state.get("final_content") or ""
            if not body:
                raise UpstreamError("Agent failed to produce email body")

            md = final_state.get("metadata") or {}
            if subject is None:
                subject = md.get("subject")

        if not subject:
            subject = "(no subject)"

        log = EmailLog(
            company_id=company_id,
            triggered_by_user_id=user_id,
            agent_run_id=agent_run_id,
            to_address=str(payload.to_address),
            from_address=settings.ses_sender_email,
            subject=subject,
            body=body,
            status="pending_approval",
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        return EmailResponse.model_validate(log)

    async def approve_and_send(
        self,
        db: AsyncSession,
        *,
        company_id: str,
        payload: ApproveEmailRequest,
    ) -> EmailResponse:
        r = await db.execute(
            select(EmailLog).where(
                EmailLog.id == payload.email_id, EmailLog.company_id == company_id
            )
        )
        log = r.scalar_one_or_none()
        if log is None:
            raise NotFoundError("Email not found")
        if log.status != "pending_approval":
            raise ConflictError(f"Email is not pending approval (status={log.status})")

        if not payload.approve:
            log.status = "rejected"
            await db.commit()
            await db.refresh(log)
            return EmailResponse.model_validate(log)

        # Approved — send via SES.
        log.status = "approved"
        await db.commit()

        try:
            message_id = await self._send_via_ses(
                to_address=log.to_address,
                from_address=log.from_address,
                subject=log.subject,
                body=log.body,
            )
            log.ses_message_id = message_id
            log.status = "sent"
            logger.info(f"Email {log.id} sent (ses_id={message_id})")
        except Exception as e:
            logger.exception(f"SES send failed for email {log.id}")
            log.status = "send_failed"
            log.error = str(e)[:5000]

        await db.commit()
        await db.refresh(log)
        return EmailResponse.model_validate(log)

    async def list_for_company(
        self, db: AsyncSession, *, company_id: str, limit: int = 50
    ) -> EmailListResponse:
        r = await db.execute(
            select(EmailLog)
            .where(EmailLog.company_id == company_id)
            .order_by(EmailLog.created_at.desc())
            .limit(limit)
        )
        logs = list(r.scalars())
        return EmailListResponse(
            emails=[EmailResponse.model_validate(x) for x in logs], total=len(logs)
        )

    # ------------------------------------------------------------------
    # Internal: SES send via aioboto3
    # ------------------------------------------------------------------
    async def _send_via_ses(
        self, *, to_address: str, from_address: str, subject: str, body: str
    ) -> str:
        """
        Send an email via Amazon SES and return the SES Message ID.

        SES sandbox note
        ----------------
        New AWS accounts are in the SES sandbox: you can only send TO and
        FROM verified addresses, max 200/day, 1/sec. To go to production
        you submit a Sending Limit Increase request. Our setup script
        (infra/aws/setup_ses.sh) covers verification.

        On error: raises UpstreamError. The caller (approve_and_send) catches
        this and persists status=send_failed + the error message.
        """
        # Lazy import keeps aioboto3 out of the hot path for non-email work.
        import aioboto3
        from botocore.exceptions import ClientError

        session_kwargs: dict = {"region_name": settings.aws_region}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            session_kwargs.update(
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )
        session = aioboto3.Session(**session_kwargs)

        try:
            async with session.client("ses") as ses:
                resp = await ses.send_email(
                    Source=from_address,
                    Destination={"ToAddresses": [to_address]},
                    Message={
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {
                            # We send text/plain; a future enhancement is HTML
                            # rendering of markdown drafts.
                            "Text": {"Data": body, "Charset": "UTF-8"},
                        },
                    },
                )
            message_id = resp["MessageId"]
            logger.info(
                f"SES send ok: to={to_address} subject={subject!r} "
                f"message_id={message_id}"
            )
            return message_id
        except ClientError as e:
            # Common SES errors:
            # - MessageRejected: sandbox + unverified recipient
            # - SendingPausedException: account-level pause (high bounce rate)
            # - Throttling: rate limit
            err = e.response.get("Error", {})
            code = err.get("Code", "Unknown")
            msg = err.get("Message", str(e))
            logger.error(f"SES send failed [{code}]: {msg}")
            raise UpstreamError(f"SES [{code}]: {msg}") from e


email_service = EmailService()