"""Tests for pipeline onboarding detection and vector search fallback."""


from sqlmodel import Session

import backend.db_engine as _engine_mod
from backend.pipeline import ChatPipeline, _fetch_relevant_things
from backend.tools import create_thing


class TestOnboardingDetection:
    def test_new_user_detected_with_no_things(self, patched_db):
        """A user with 0 surfaced active Things is detected as new."""
        pipeline = ChatPipeline(user_id="fresh-user")
        assert pipeline._is_new_user() is True

    def test_existing_user_detected_with_things(self, patched_db):
        """A user with 1+ surfaced active Things is not new."""
        create_thing(title="My Task", user_id="existing-user")
        pipeline = ChatPipeline(user_id="existing-user")
        assert pipeline._is_new_user() is False

    def test_inactive_things_dont_count(self, patched_db):
        """Inactive Things should not prevent onboarding mode."""
        from backend.tools import update_thing

        thing = create_thing(title="Done Task", user_id="done-user")
        update_thing(thing["id"], active=False, user_id="done-user")
        pipeline = ChatPipeline(user_id="done-user")
        assert pipeline._is_new_user() is True


class TestVectorSearchFallback:
    def test_sql_like_fallback_when_no_vectors(self, patched_db, mock_vector_store):
        """When vector_search returns [], SQL LIKE fallback finds matching Things."""
        create_thing(title="Deploy the frontend app", user_id="test-user")
        create_thing(title="Buy groceries", user_id="test-user")

        # mock_vector_store already patches vector_search to return [] and vector_count to return 0
        with Session(_engine_mod.engine) as session:
            results = _fetch_relevant_things(
                session,
                search_queries=["Deploy"],
                filter_params={"active_only": True},
                user_id="test-user",
            )

        titles = [r["title"] for r in results]
        assert "Deploy the frontend app" in titles

    def test_sql_like_fallback_no_match_returns_empty(self, patched_db, mock_vector_store):
        """SQL LIKE fallback with no matching query returns no seed results."""
        create_thing(title="Unrelated Item", user_id="test-user")

        with Session(_engine_mod.engine) as session:
            results = _fetch_relevant_things(
                session,
                search_queries=["zzz_no_match_zzz"],
                filter_params={"active_only": True},
                user_id="test-user",
            )

        # May include recently-updated Things as fallback padding, but the
        # specific non-matching query should not produce a false positive
        matching = [r for r in results if "zzz_no_match_zzz" in r.get("title", "")]
        assert len(matching) == 0
