"""Tests for user_id ownership checks in tools.py (issue #435).

Verifies that update_thing, delete_thing, merge_things, delete_relationship,
and create_relationship reject operations when user_id doesn't match the
Thing's owner.
"""

from backend.tools import (
    create_thing,
    update_thing,
    delete_thing,
    merge_things,
    create_relationship,
    delete_relationship,
    get_user_profile,
)


USER_A = "user-a"
USER_B = "user-b"


def _make_thing(title: str = "Test Thing", user_id: str = USER_A) -> dict:
    result = create_thing(title=title, user_id=user_id)
    assert "id" in result, f"Failed to create thing: {result}"
    return result


class TestUpdateThingIsolation:
    def test_owner_can_update(self, patched_db):
        thing = _make_thing()
        result = update_thing(thing["id"], title="Updated", user_id=USER_A)
        assert result.get("title") == "Updated"
        assert "error" not in result

    def test_other_user_cannot_update(self, patched_db):
        thing = _make_thing()
        result = update_thing(thing["id"], title="Hacked", user_id=USER_B)
        assert result == {"error": "Unauthorized"}

    def test_no_user_id_skips_check(self, patched_db):
        """When no user_id is provided (e.g. system/admin), allow access."""
        thing = _make_thing()
        result = update_thing(thing["id"], title="System Update", user_id="")
        assert result.get("title") == "System Update"


class TestDeleteThingIsolation:
    def test_owner_can_delete(self, patched_db):
        thing = _make_thing()
        result = delete_thing(thing["id"], user_id=USER_A)
        assert result.get("deleted") == thing["id"]

    def test_other_user_cannot_delete(self, patched_db):
        thing = _make_thing()
        result = delete_thing(thing["id"], user_id=USER_B)
        assert result == {"error": "Unauthorized"}


class TestMergeThingsIsolation:
    def test_owner_can_merge(self, patched_db):
        keep = _make_thing(title="Keep")
        remove = _make_thing(title="Remove")
        result = merge_things(keep["id"], remove["id"], user_id=USER_A)
        assert result.get("keep_id") == keep["id"]

    def test_other_user_cannot_merge_keep(self, patched_db):
        keep = _make_thing(title="Keep")
        remove = _make_thing(title="Remove")
        result = merge_things(keep["id"], remove["id"], user_id=USER_B)
        assert result == {"error": "Unauthorized"}

    def test_other_user_cannot_merge_remove(self, patched_db):
        """Even if user owns keep but not remove, merge is rejected."""
        keep = _make_thing(title="Keep", user_id=USER_B)
        remove = _make_thing(title="Remove", user_id=USER_A)
        result = merge_things(keep["id"], remove["id"], user_id=USER_B)
        assert result == {"error": "Unauthorized"}


class TestDeleteRelationshipIsolation:
    def test_owner_can_delete_relationship(self, patched_db):
        t1 = _make_thing(title="Thing 1")
        t2 = _make_thing(title="Thing 2")
        rel = create_relationship(t1["id"], t2["id"], "related", user_id=USER_A)
        assert "id" in rel

        result = delete_relationship(rel["id"], user_id=USER_A)
        assert result == {"ok": True}

    def test_other_user_cannot_delete_relationship(self, patched_db):
        t1 = _make_thing(title="Thing 1")
        t2 = _make_thing(title="Thing 2")
        rel = create_relationship(t1["id"], t2["id"], "related", user_id=USER_A)
        assert "id" in rel

        result = delete_relationship(rel["id"], user_id=USER_B)
        assert result == {"error": "Unauthorized"}


class TestCreateRelationshipIsolation:
    def test_other_user_cannot_create_relationship(self, patched_db):
        t1 = _make_thing(title="Thing 1")
        t2 = _make_thing(title="Thing 2")
        result = create_relationship(t1["id"], t2["id"], "related", user_id=USER_B)
        assert result == {"error": "Unauthorized"}


class TestGetUserProfileIsolation:
    def test_user_sees_own_profile(self, patched_db):
        create_thing(title="Alice", type_hint="person", user_id=USER_A)
        result = get_user_profile(user_id=USER_A)
        assert "error" not in result
        assert result["thing"]["title"] == "Alice"

    def test_user_cannot_see_other_profile(self, patched_db):
        create_thing(title="Alice", type_hint="person", user_id=USER_A)
        result = get_user_profile(user_id=USER_B)
        assert result == {"error": "User profile Thing not found"}

    def test_no_user_id_returns_first_person(self, patched_db):
        """Empty user_id bypasses filter (system/admin access)."""
        create_thing(title="Alice", type_hint="person", user_id=USER_A)
        result = get_user_profile(user_id="")
        assert "error" not in result
