"""Browser push notification subscription management."""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user
from ..config import settings
from ..database import db
from ..models import PushSubscription, PushSubscriptionCreate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/push", tags=["push"])

_VAPID_KEY_PATH = Path(settings.DATA_DIR) / "vapid_keys.json"


def _load_or_generate_vapid_keys() -> dict:
    """Load VAPID keys from disk or generate new ones."""
    if _VAPID_KEY_PATH.exists():
        with open(_VAPID_KEY_PATH) as f:
            return json.load(f)

    from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )
    import base64

    private_key = generate_private_key(SECP256R1())
    private_bytes = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public_bytes = private_key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)

    keys = {
        "public_key": base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode(),
        "private_key_pem": private_bytes.decode(),
    }
    _VAPID_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_VAPID_KEY_PATH, "w") as f:
        json.dump(keys, f)
    logger.info("Generated new VAPID key pair")
    return keys


@router.get("/vapid-key", summary="Get VAPID public key for push subscriptions")
def get_vapid_key() -> dict:
    """Return the VAPID public key. Used by frontend to create push subscriptions."""
    try:
        keys = _load_or_generate_vapid_keys()
        return {"public_key": keys["public_key"]}
    except Exception as e:
        logger.error("Failed to load/generate VAPID keys: %s", e)
        raise HTTPException(status_code=500, detail="Push notifications not available")


@router.post("/subscribe", response_model=PushSubscription, summary="Subscribe to push notifications")
def subscribe_push(
    body: PushSubscriptionCreate,
    user_id: str = Depends(require_user),
) -> PushSubscription:
    """Store a browser push subscription endpoint."""
    sub_id = str(uuid.uuid4())
    notification_types_str = ",".join(body.notification_types)
    now = datetime.utcnow()

    with db() as conn:
        # Upsert by endpoint
        existing = conn.execute(
            "SELECT id FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
            (user_id, body.endpoint),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE push_subscriptions
                   SET p256dh = ?, auth = ?, notification_types = ?, updated_at = ?
                   WHERE id = ?""",
                (body.p256dh, body.auth, notification_types_str, now.isoformat(), existing["id"]),
            )
            sub_id = existing["id"]
        else:
            conn.execute(
                """INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth, notification_types, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (sub_id, user_id, body.endpoint, body.p256dh, body.auth, notification_types_str, now.isoformat(), now.isoformat()),
            )

    return PushSubscription(
        id=sub_id,
        endpoint=body.endpoint,
        notification_types=body.notification_types,
        created_at=now,
    )


@router.delete("/subscribe", summary="Unsubscribe from push notifications")
def unsubscribe_push(
    endpoint: str,
    user_id: str = Depends(require_user),
) -> dict:
    """Remove a push subscription."""
    with db() as conn:
        conn.execute(
            "DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
            (user_id, endpoint),
        )
    return {"ok": True}


@router.get("/subscriptions", response_model=list[PushSubscription], summary="List push subscriptions")
def list_subscriptions(user_id: str = Depends(require_user)) -> list[PushSubscription]:
    """Return all push subscriptions for the current user."""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM push_subscriptions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()

    return [
        PushSubscription(
            id=r["id"],
            endpoint=r["endpoint"],
            notification_types=r["notification_types"].split(",") if r["notification_types"] else [],
            created_at=datetime.fromisoformat(r["created_at"]),
        )
        for r in rows
    ]
