"""Tests for accept_suggestion cross-user ownership check."""

from datetime import datetime, timezone


def _seed(db, owner_from: str, owner_to: str) -> None:
    """Create two Things and a pending connection suggestion between them."""
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        # Ensure user records exist for FK constraints
        for uid in {owner_from, owner_to}:
            conn.execute(
                "INSERT OR IGNORE INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                (uid, f"{uid}@test.com", f"g-{uid}", uid),
            )
        conn.execute(
            "INSERT INTO things (id, title, user_id, active, surface, created_at, updated_at) VALUES (?, ?, ?, 1, 1, ?, ?)",
            ("t-from", "From Thing", owner_from, now, now),
        )
        conn.execute(
            "INSERT INTO things (id, title, user_id, active, surface, created_at, updated_at) VALUES (?, ?, ?, 1, 1, ?, ?)",
            ("t-to", "To Thing", owner_to, now, now),
        )
        conn.execute(
            "INSERT INTO connection_suggestions (id, from_thing_id, to_thing_id, suggested_relationship_type, reason, status, user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("sug-1", "t-from", "t-to", "related-to", "test", "pending", owner_from, now),
        )


class TestAcceptOwnershipCheck:
    def test_accept_rejects_when_user_does_not_own_to_thing(self, user_a_client, db):
        """User A cannot accept a suggestion referencing User B's Thing."""
        _seed(db, owner_from="user-a", owner_to="other-user")
        resp = user_a_client.post("/api/connections/suggestions/sug-1/accept")
        assert resp.status_code == 404

    def test_accept_succeeds_when_user_owns_both_things(self, user_a_client, db):
        """User A can accept a suggestion when both Things belong to them."""
        _seed(db, owner_from="user-a", owner_to="user-a")
        resp = user_a_client.post("/api/connections/suggestions/sug-1/accept")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
