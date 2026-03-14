"""Tests for SNAG scoring integration."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("SERVICE_API_KEY", "test-key")
os.environ.setdefault("ENVIRONMENT", "test")


class TestScoringEnabled:
    def test_disabled_by_default(self):
        """Scoring is disabled when SNAG_RUNNER_URL is empty."""
        from app.core.config import get_settings
        get_settings.cache_clear()
        os.environ.pop("SNAG_RUNNER_URL", None)
        os.environ.pop("SNAG_AUTO_SCORE", None)
        get_settings.cache_clear()

        from app.core.scoring import scoring_enabled
        assert scoring_enabled() is False
        get_settings.cache_clear()

    def test_disabled_when_url_set_but_auto_score_false(self):
        """Scoring is disabled when SNAG_RUNNER_URL set but SNAG_AUTO_SCORE is false."""
        from app.core.config import get_settings
        get_settings.cache_clear()
        os.environ["SNAG_RUNNER_URL"] = "http://snag.internal"
        os.environ["SNAG_AUTO_SCORE"] = "false"
        get_settings.cache_clear()

        from app.core.scoring import scoring_enabled
        assert scoring_enabled() is False

        del os.environ["SNAG_RUNNER_URL"]
        del os.environ["SNAG_AUTO_SCORE"]
        get_settings.cache_clear()

    def test_enabled_when_both_set(self):
        """Scoring is enabled when both SNAG_RUNNER_URL and SNAG_AUTO_SCORE=true."""
        from app.core.config import get_settings
        get_settings.cache_clear()
        os.environ["SNAG_RUNNER_URL"] = "http://snag.internal"
        os.environ["SNAG_AUTO_SCORE"] = "true"
        get_settings.cache_clear()

        from app.core.scoring import scoring_enabled
        assert scoring_enabled() is True

        del os.environ["SNAG_RUNNER_URL"]
        del os.environ["SNAG_AUTO_SCORE"]
        get_settings.cache_clear()


class TestAggregateScore:
    def test_none_when_no_scores(self):
        from app.core.scoring import aggregate_score
        assert aggregate_score(None) is None
        assert aggregate_score({}) is None

    def test_mean_of_all_axes(self):
        from app.core.scoring import aggregate_score
        scores = {"GSR": 1.0, "TCS": 0.8, "WMNED": 0.6, "GCQ": 0.4, "HTP": 0.2}
        result = aggregate_score(scores)
        assert result == pytest.approx(0.6, abs=1e-6)

    def test_ignores_unknown_axes(self):
        from app.core.scoring import aggregate_score
        scores = {"GSR": 1.0, "UNKNOWN": 0.0}
        result = aggregate_score(scores)
        assert result == pytest.approx(1.0)

    def test_partial_axes(self):
        from app.core.scoring import aggregate_score
        scores = {"GSR": 0.8, "TCS": 0.6}
        result = aggregate_score(scores)
        assert result == pytest.approx(0.7, abs=1e-6)


class TestScoreMoment:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_url(self):
        """score_moment returns None when SNAG_RUNNER_URL is not set."""
        from app.core.config import get_settings
        get_settings.cache_clear()
        os.environ.pop("SNAG_RUNNER_URL", None)
        get_settings.cache_clear()

        from app.core.scoring import score_moment
        result = await score_moment("/test/moment", {"name": "Test"})
        assert result is None
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_calls_score_endpoint(self):
        """score_moment calls /score endpoint and returns parsed axes."""
        from app.core.config import get_settings
        get_settings.cache_clear()
        os.environ["SNAG_RUNNER_URL"] = "http://snag.internal"
        get_settings.cache_clear()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={
            "scores": {
                "GSR": 0.9, "TCS": 0.8, "WMNED": 0.7, "GCQ": 0.6, "HTP": 0.5,
            }
        })

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.core.scoring.httpx.AsyncClient", return_value=mock_client):
            from app.core.scoring import score_moment
            result = await score_moment("/test/moment", {"name": "Test moment"})

        assert result is not None
        assert result["GSR"] == pytest.approx(0.9)
        assert result["TCS"] == pytest.approx(0.8)
        assert result["WMNED"] == pytest.approx(0.7)
        assert result["GCQ"] == pytest.approx(0.6)
        assert result["HTP"] == pytest.approx(0.5)

        del os.environ["SNAG_RUNNER_URL"]
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_returns_none_on_http_error(self):
        """score_moment returns None when runner returns an error."""
        from app.core.config import get_settings
        get_settings.cache_clear()
        os.environ["SNAG_RUNNER_URL"] = "http://snag.internal"
        get_settings.cache_clear()

        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Not Found", request=MagicMock(), response=MagicMock(
                    status_code=404, text="Not found"
                )
            )
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.core.scoring.httpx.AsyncClient", return_value=mock_client):
            from app.core.scoring import score_moment
            result = await score_moment("/test/moment", {"name": "Test"})

        assert result is None

        del os.environ["SNAG_RUNNER_URL"]
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_clamps_scores_to_range(self):
        """score_moment clamps returned values to [0.0, 1.0]."""
        from app.core.config import get_settings
        get_settings.cache_clear()
        os.environ["SNAG_RUNNER_URL"] = "http://snag.internal"
        get_settings.cache_clear()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={
            "scores": {"GSR": 1.5, "TCS": -0.2, "WMNED": 0.5, "GCQ": 0.5, "HTP": 0.5}
        })

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.core.scoring.httpx.AsyncClient", return_value=mock_client):
            from app.core.scoring import score_moment
            result = await score_moment("/test/moment", {"name": "Test"})

        assert result["GSR"] == pytest.approx(1.0)
        assert result["TCS"] == pytest.approx(0.0)

        del os.environ["SNAG_RUNNER_URL"]
        get_settings.cache_clear()


class TestScheduleScoring:
    def test_no_op_when_disabled(self):
        """schedule_scoring does nothing when scoring is disabled."""
        from app.core.config import get_settings
        get_settings.cache_clear()
        os.environ.pop("SNAG_RUNNER_URL", None)
        os.environ.pop("SNAG_AUTO_SCORE", None)
        get_settings.cache_clear()

        pool = MagicMock()
        with patch("app.core.scoring.asyncio.create_task") as mock_create:
            from app.core.scoring import schedule_scoring
            schedule_scoring(pool, "/test/moment", {"name": "Test"})
            mock_create.assert_not_called()
        get_settings.cache_clear()
