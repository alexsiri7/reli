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


def _delete_where(session: Session, model: type, clause: Any) -> None:
    """Delete all records of `model` matching `clause`."""
    for r in session.exec(select(model).where(clause)).all():
        session.delete(r)


@router.get("/export")
def export_user_data(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict:
    """Export all user data as structured JSON (GDPR data portability)."""
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

    # Thing embeddings (exclude raw vector — not human-readable PII)
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
    }


@router.delete("/delete-all")
def delete_all_user_data(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Response:
    """Permanently delete all user data (GDPR right to erasure)."""
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete-all without authenticated user",
        )

    # Collect IDs needed for junction/child tables
    things = session.exec(select(ThingRecord).where(user_filter_clause(ThingRecord.user_id, user_id))).all()
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

    # 1. ChatMessageUsageRecord (FK → chat_history)
    if chat_msg_ids:
        _delete_where(session, ChatMessageUsageRecord, ChatMessageUsageRecord.chat_message_id.in_(chat_msg_ids))  # type: ignore[attr-defined]

    # 2. ThingEmbeddingRecord (FK → things)
    if thing_ids:
        _delete_where(session, ThingEmbeddingRecord, ThingEmbeddingRecord.thing_id.in_(thing_ids))  # type: ignore[attr-defined]

    # 3. ThingRelationshipRecord (FK → things, no user_id)
    if thing_ids:
        _delete_where(
            session,
            ThingRelationshipRecord,
            or_(
                ThingRelationshipRecord.from_thing_id.in_(thing_ids),  # type: ignore[attr-defined]
                ThingRelationshipRecord.to_thing_id.in_(thing_ids),  # type: ignore[attr-defined]
            ),
        )

    # 4. SweepFindingRecord (FK → things)
    _delete_where(session, SweepFindingRecord, user_filter_clause(SweepFindingRecord.user_id, user_id))

    # 5. ConnectionSuggestionRecord (FK → things)
    _delete_where(session, ConnectionSuggestionRecord, user_filter_clause(ConnectionSuggestionRecord.user_id, user_id))

    # 6. ScheduledTaskRecord (FK → things, users)
    _delete_where(session, ScheduledTaskRecord, user_filter_clause(ScheduledTaskRecord.user_id, user_id))

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
    _delete_where(session, ConversationSummaryRecord, ConversationSummaryRecord.user_id == user_id)

    # 11. UserSettingRecord (FK → users)
    _delete_where(session, UserSettingRecord, UserSettingRecord.user_id == user_id)

    # 12. GoogleTokenRecord (FK → users)
    _delete_where(session, GoogleTokenRecord, user_filter_clause(GoogleTokenRecord.user_id, user_id))

    # 13. Tables with FK → users or standalone user_id
    _delete_where(session, SweepRunRecord, user_filter_clause(SweepRunRecord.user_id, user_id))
    _delete_where(session, SweepActionRecord, user_filter_clause(SweepActionRecord.user_id, user_id))
    _delete_where(session, UsageLogRecord, user_filter_clause(UsageLogRecord.user_id, user_id))
    _delete_where(session, MorningBriefingRecord, user_filter_clause(MorningBriefingRecord.user_id, user_id))
    _delete_where(session, WeeklyBriefingRecord, user_filter_clause(WeeklyBriefingRecord.user_id, user_id))
    _delete_where(session, NudgeDismissalRecord, NudgeDismissalRecord.user_id == user_id)
    _delete_where(session, NudgeSuppressionRecord, NudgeSuppressionRecord.user_id == user_id)
    _delete_where(session, MergeHistoryRecord, user_filter_clause(MergeHistoryRecord.user_id, user_id))
    _delete_where(session, ThingTypeRecord, user_filter_clause(ThingTypeRecord.user_id, user_id))

    # 14. GmailOAuthStateRecord (PK is user_id)
    gmail_state = session.exec(select(GmailOAuthStateRecord).where(GmailOAuthStateRecord.user_id == user_id)).first()
    if gmail_state:
        session.delete(gmail_state)

    # 15. UserRecord (last — everything else FK'd to it)
    user_record = session.exec(select(UserRecord).where(UserRecord.id == user_id)).first()
    if user_record:
        session.delete(user_record)

    session.commit()

    logger.info("GDPR delete-all completed for user_id=%s", user_id)

    response = Response(status_code=status.HTTP_200_OK)
    response.delete_cookie(COOKIE_NAME)
    return response
