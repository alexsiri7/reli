"""Tests for tools.create_thing(), update_thing(), delete_thing() basic coverage."""

from backend.tools import create_thing, update_thing, delete_thing, get_thing


class TestCreateThing:
    def test_minimal_fields(self, patched_db):
        result = create_thing(title="My Task")
        assert "id" in result
        assert result["title"] == "My Task"
        assert result["active"] is True
        assert result["surface"] is True  # no type_hint → defaults to surface=true

    def test_nonsurface_type_defaults_surface_false(self, patched_db):
        result = create_thing(title="John Doe", type_hint="person")
        assert result["surface"] is False

    def test_custom_type_defaults_surface_true(self, patched_db):
        result = create_thing(title="Trip to Japan", type_hint="trip")
        assert result["surface"] is True
        assert result["type_hint"] == "trip"

    def test_custom_type_surface_false_when_explicit(self, patched_db):
        result = create_thing(title="My Recipe", type_hint="recipe", surface=False)
        assert result["surface"] is False
        assert result["type_hint"] == "recipe"

    def test_with_open_questions(self, patched_db):
        result = create_thing(
            title="Research Topic",
            open_questions_json='["What is X?", "How does Y work?"]',
        )
        assert result["open_questions"] == ["What is X?", "How does Y work?"]
        # Verify persistence
        fetched = get_thing(result["id"])
        assert fetched["open_questions"] == ["What is X?", "How does Y work?"]


class TestUpdateThing:
    def test_change_title(self, patched_db):
        thing = create_thing(title="Old Title")
        updated = update_thing(thing_id=thing["id"], title="New Title")
        assert updated["title"] == "New Title"

    def test_set_active_false(self, patched_db):
        thing = create_thing(title="Active Thing")
        updated = update_thing(thing_id=thing["id"], active=False)
        assert updated["active"] is False


class TestDeleteThing:
    def test_delete_removes_thing(self, patched_db):
        thing = create_thing(title="To Delete")
        result = delete_thing(thing_id=thing["id"])
        assert result["deleted"] == thing["id"]
        # Verify it's gone
        fetched = get_thing(thing["id"])
        assert "error" in fetched
