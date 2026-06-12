"""GDPR right-to-erasure and data export endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_
from sqlmodel import Session, select

from ..auth import COOKIE_NAME, require_user
from ..db_engine import get_session, user_filter_clause
from ..db_models import (
    ChatHistoryRecord,
    ChatMessageUsageRecord,
    ChatSessionRecord,
    ConnectionSuggestionRecord,
    ConversationSummaryRecord,
    GmailOAuthStateRecord,
    GoogleTokenRecord,
    McpAuthCodeRecord,
    McpRefreshTokenRecord,
    MergeHistoryRecord,
    MorningBriefingRecord,
    NudgeDismissalRecord,
    NudgeSuppressionRecord,
    ScheduledTaskRecord,
    SweepActionRecord,
    SweepFindingRecord,
    SweepRunRecord,
    ThingEmbeddingRecord,
    ThingRecord,
    ThingRelationshipRecord,
    ThingTypeRecord,
    UsageLogRecord,
    UserRecord,
    UserSettingRecord,
    WeeklyBriefingRecord,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gdpr", tags=["gdpr"])

# Setting keys whose values must be redacted in export
_REDACTED_SETTING_KEYS = {"requesty_api_key", "openai_api_key"}

# Google token fields that contain secrets
_REDACTED_GOOGLE_FIELDS = {"access_token", "refresh_token", "client_secret"}


@router.get("/export")
def export_user_data(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict:
    """Export all user data as structured JSON (GDPR data portability)."""
    try:
        return _export_user_data_inner(user_id, session)
    except Exception:
        logger.exception("GDPR export failed for user_id=%s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export user data. Please try again.",
        )


def _export_user_data_inner(user_id: str, session: Session) -> dict:
    # Things
    things = session.exec(select(ThingRecord).where(user_filter_clause(ThingRecord.user_id, user_id))).all()
    thing_ids = [t.id for t in things]

    # Thing relationships (no user_id column — filter via thing_ids)
    relationships: list[Any] = []
    if thing_ids:
        relationships = list(
            session.exec(
                select(ThingRelationshipRecord).where(
                    or_(
                        ThingRelationshipRecord.from_thing_id.in_(thing_ids),  # type: ignore[attr-defined]
                        ThingRelationshipRecord.to_thing_id.in_(thing_ids),  # type: ignore[attr-defined]
                    )
                )
            ).all()
        )

    # Thing embeddings — omit raw vector (binary/unreadable); include text content instead
    embeddings = []
    if thing_ids:
        raw_embeddings = session.exec(
            select(ThingEmbeddingRecord).where(
                ThingEmbeddingRecord.thing_id.in_(thing_ids)  # type: ignore[attr-defined]
            )
        ).all()
        embeddings = [
            {
                "thing_id": e.thing_id,
                "content": e.content,
                "updated_at": e.updated_at.isoformat() if e.updated_at else None,
            }
            for e in raw_embeddings
        ]

    # Chat sessions and history
    chat_sessions = session.exec(select(ChatSessionRecord).where(ChatSessionRecord.user_id == user_id)).all()
    session_ids = [s.id for s in chat_sessions]

    chat_history: list[Any] = []
    if session_ids:
        chat_history = list(
            session.exec(
                select(ChatHistoryRecord).where(
                    ChatHistoryRecord.session_id.in_(session_ids)  # type: ignore[attr-defined]
                )
            ).all()
        )

    # Conversation summaries
    conversation_summaries = session.exec(
        select(ConversationSummaryRecord).where(ConversationSummaryRecord.user_id == user_id)
    ).all()

    # User settings (redact API keys)
    raw_settings = session.exec(select(UserSettingRecord).where(UserSettingRecord.user_id == user_id)).all()
    settings_data = []
    for s in raw_settings:
        d = s.model_dump()
        if s.key in _REDACTED_SETTING_KEYS:
            d["value"] = "[REDACTED]"
        settings_data.append(d)

    # Google tokens (redact secrets)
    raw_google_tokens = session.exec(
        select(GoogleTokenRecord).where(user_filter_clause(GoogleTokenRecord.user_id, user_id))
    ).all()
    google_tokens_data = []
    for gt in raw_google_tokens:
        d = gt.model_dump()
        for field in _REDACTED_GOOGLE_FIELDS:
            if field in d:
                d[field] = "[REDACTED]"
        google_tokens_data.append(d)

    # Remaining tables — all queried by user_id or user_filter_clause
    sweep_findings = session.exec(
        select(SweepFindingRecord).where(user_filter_clause(SweepFindingRecord.user_id, user_id))
    ).all()
    sweep_runs = session.exec(select(SweepRunRecord).where(user_filter_clause(SweepRunRecord.user_id, user_id))).all()
    sweep_actions = session.exec(
        select(SweepActionRecord).where(user_filter_clause(SweepActionRecord.user_id, user_id))
    ).all()
    usage_log = session.exec(select(UsageLogRecord).where(user_filter_clause(UsageLogRecord.user_id, user_id))).all()
    morning_briefings = session.exec(
        select(MorningBriefingRecord).where(user_filter_clause(MorningBriefingRecord.user_id, user_id))
    ).all()
    weekly_briefings = session.exec(
        select(WeeklyBriefingRecord).where(user_filter_clause(WeeklyBriefingRecord.user_id, user_id))
    ).all()
    connection_suggestions = session.exec(
        select(ConnectionSuggestionRecord).where(user_filter_clause(ConnectionSuggestionRecord.user_id, user_id))
    ).all()
    nudge_dismissals = session.exec(select(NudgeDismissalRecord).where(NudgeDismissalRecord.user_id == user_id)).all()
    nudge_suppressions = session.exec(
        select(NudgeSuppressionRecord).where(NudgeSuppressionRecord.user_id == user_id)
    ).all()
    merge_history = session.exec(
        select(MergeHistoryRecord).where(user_filter_clause(MergeHistoryRecord.user_id, user_id))
    ).all()
    thing_types = session.exec(
        select(ThingTypeRecord).where(user_filter_clause(ThingTypeRecord.user_id, user_id))
    ).all()
    scheduled_tasks = session.exec(
        select(ScheduledTaskRecord).where(user_filter_clause(ScheduledTaskRecord.user_id, user_id))
    ).all()

    # MCP refresh tokens (omit refresh_token value — it's a secret)
    mcp_refresh_tokens = [
        {"user_id": r.user_id, "client_id": r.client_id, "scope": r.scope, "expires_at": r.expires_at}
        for r in session.exec(select(McpRefreshTokenRecord).where(McpRefreshTokenRecord.user_id == user_id)).all()
    ]

    # MCP auth codes (omit auth_code + code_challenge — secrets)
    mcp_auth_codes = [
        {
            "user_id": r.user_id,
            "email": r.email,
            "client_id": r.client_id,
            "redirect_uri": r.redirect_uri,
            "expires_at": r.expires_at,
        }
        for r in session.exec(select(McpAuthCodeRecord).where(McpAuthCodeRecord.user_id == user_id)).all()
    ]

    # Gmail OAuth state (omit state token — CSRF secret)
    gmail_oauth_state_record = session.exec(
        select(GmailOAuthStateRecord).where(GmailOAuthStateRecord.user_id == user_id)
    ).first()
    gmail_oauth_state = (
        {"user_id": gmail_oauth_state_record.user_id, "expires_at": gmail_oauth_state_record.expires_at}
        if gmail_oauth_state_record
        else None
    )

    # User record
    user_record = session.exec(select(UserRecord).where(UserRecord.id == user_id)).first()

    return {
        "user": user_record.model_dump() if user_record else None,
        "things": [t.model_dump() for t in things],
        "relationships": [r.model_dump() for r in relationships],
        "embeddings": embeddings,
        "chat_sessions": [s.model_dump() for s in chat_sessions],
        "chat_history": [m.model_dump() for m in chat_history],
        "conversation_summaries": [cs.model_dump() for cs in conversation_summaries],
        "settings": settings_data,
        "google_tokens": google_tokens_data,
        "sweep_findings": [f.model_dump() for f in sweep_findings],
        "sweep_runs": [r.model_dump() for r in sweep_runs],
        "sweep_actions": [a.model_dump() for a in sweep_actions],
        "usage_log": [u.model_dump() for u in usage_log],
        "morning_briefings": [b.model_dump() for b in morning_briefings],
        "weekly_briefings": [b.model_dump() for b in weekly_briefings],
        "connection_suggestions": [c.model_dump() for c in connection_suggestions],
        "nudge_dismissals": [n.model_dump() for n in nudge_dismissals],
        "nudge_suppressions": [n.model_dump() for n in nudge_suppressions],
        "merge_history": [m.model_dump() for m in merge_history],
        "thing_types": [t.model_dump() for t in thing_types],
        "scheduled_tasks": [t.model_dump() for t in scheduled_tasks],
        "mcp_refresh_tokens": mcp_refresh_tokens,
        "mcp_auth_codes": mcp_auth_codes,
        "gmail_oauth_state": gmail_oauth_state,
    }


@router.delete("/delete-all")
def delete_all_user_data(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Response:
    """Permanently delete all user data (GDPR right to erasure)."""
    # Collect IDs needed for junction/child tables
    things = session.exec(select(ThingRecord).where(ThingRecord.user_id == user_id)).all()
    thing_ids = [t.id for t in things]

    chat_sessions = session.exec(select(ChatSessionRecord).where(ChatSessionRecord.user_id == user_id)).all()
    session_ids = [s.id for s in chat_sessions]

    chat_messages: list[Any] = []
    if session_ids:
        chat_messages = list(
            session.exec(
                select(ChatHistoryRecord).where(
                    ChatHistoryRecord.session_id.in_(session_ids)  # type: ignore[attr-defined]
                )
            ).all()
        )
    chat_msg_ids = [m.id for m in chat_messages]

    # Delete in FK-safe order (children before parents)
    # r is typed Any because it's reused across heterogeneous delete loops.
    r: Any

    try:
        # 1. ChatMessageUsageRecord (FK → chat_history)
        if chat_msg_ids:
            for r in session.exec(
                select(ChatMessageUsageRecord).where(
                    ChatMessageUsageRecord.chat_message_id.in_(chat_msg_ids)  # type: ignore[attr-defined]
                )
            ).all():
                session.delete(r)

        # 2. ThingEmbeddingRecord (FK → things)
        if thing_ids:
            for r in session.exec(
                select(ThingEmbeddingRecord).where(
                    ThingEmbeddingRecord.thing_id.in_(thing_ids)  # type: ignore[attr-defined]
                )
            ).all():
                session.delete(r)

        # 3. ThingRelationshipRecord (FK → things, no user_id)
        if thing_ids:
            for r in session.exec(
                select(ThingRelationshipRecord).where(
                    or_(
                        ThingRelationshipRecord.from_thing_id.in_(thing_ids),  # type: ignore[attr-defined]
                        ThingRelationshipRecord.to_thing_id.in_(thing_ids),  # type: ignore[attr-defined]
                    )
                )
            ).all():
                session.delete(r)

        # 4. SweepFindingRecord (FK → things)
        for r in session.exec(select(SweepFindingRecord).where(SweepFindingRecord.user_id == user_id)).all():
            session.delete(r)

        # 5. ConnectionSuggestionRecord (FK → things)
        for r in session.exec(
            select(ConnectionSuggestionRecord).where(ConnectionSuggestionRecord.user_id == user_id)
        ).all():
            session.delete(r)

        # 6. ScheduledTaskRecord (FK → things, users)
        for r in session.exec(select(ScheduledTaskRecord).where(ScheduledTaskRecord.user_id == user_id)).all():
            session.delete(r)

        # 7. ThingRecord
        for r in things:
            session.delete(r)

        # 8. ChatHistoryRecord (FK → chat_sessions)
        for r in chat_messages:
            session.delete(r)

        # 9. ChatSessionRecord
        for r in chat_sessions:
            session.delete(r)

        # 10. ConversationSummaryRecord (FK → users)
        for r in session.exec(
            select(ConversationSummaryRecord).where(ConversationSummaryRecord.user_id == user_id)
        ).all():
            session.delete(r)

        # 11. UserSettingRecord (FK → users)
        for r in session.exec(select(UserSettingRecord).where(UserSettingRecord.user_id == user_id)).all():
            session.delete(r)

        # 12. GoogleTokenRecord (FK → users)
        for r in session.exec(select(GoogleTokenRecord).where(GoogleTokenRecord.user_id == user_id)).all():
            session.delete(r)

        # 13. Tables with FK → users or standalone user_id
        for r in session.exec(select(SweepRunRecord).where(SweepRunRecord.user_id == user_id)).all():
            session.delete(r)

        for r in session.exec(select(SweepActionRecord).where(SweepActionRecord.user_id == user_id)).all():
            session.delete(r)

        for r in session.exec(select(UsageLogRecord).where(UsageLogRecord.user_id == user_id)).all():
            session.delete(r)

        for r in session.exec(select(MorningBriefingRecord).where(MorningBriefingRecord.user_id == user_id)).all():
            session.delete(r)

        for r in session.exec(select(WeeklyBriefingRecord).where(WeeklyBriefingRecord.user_id == user_id)).all():
            session.delete(r)

        for r in session.exec(select(NudgeDismissalRecord).where(NudgeDismissalRecord.user_id == user_id)).all():
            session.delete(r)

        for r in session.exec(select(NudgeSuppressionRecord).where(NudgeSuppressionRecord.user_id == user_id)).all():
            session.delete(r)

        for r in session.exec(select(MergeHistoryRecord).where(MergeHistoryRecord.user_id == user_id)).all():
            session.delete(r)

        for r in session.exec(select(ThingTypeRecord).where(ThingTypeRecord.user_id == user_id)).all():
            session.delete(r)

        # 14. McpRefreshTokenRecord and McpAuthCodeRecord (hold user_id + email PII)
        for r in session.exec(select(McpRefreshTokenRecord).where(McpRefreshTokenRecord.user_id == user_id)).all():
            session.delete(r)

        for r in session.exec(select(McpAuthCodeRecord).where(McpAuthCodeRecord.user_id == user_id)).all():
            session.delete(r)

        # 15. GmailOAuthStateRecord (PK is user_id)
        gmail_state = session.exec(
            select(GmailOAuthStateRecord).where(GmailOAuthStateRecord.user_id == user_id)
        ).first()
        if gmail_state:
            session.delete(gmail_state)

        # 16. UserRecord (last — everything else FK'd to it)
        user_record = session.exec(select(UserRecord).where(UserRecord.id == user_id)).first()
        if user_record:
            session.delete(user_record)

        session.commit()
    except Exception:
        logger.exception("GDPR delete-all failed for user_id=%s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user data. No data was deleted. Please try again.",
        )

    logger.info("GDPR delete-all completed for user_id=%s", user_id)

    response = Response(status_code=status.HTTP_200_OK)
    response.delete_cookie(COOKIE_NAME)
    return response
