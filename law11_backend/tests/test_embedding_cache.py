import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.embedding_cache import get_embedding_async


@pytest.mark.asyncio
async def test_cache_miss_calls_openai_and_saves():
    with patch("app.services.embedding_cache._get_cached_embedding", return_value=None), \
         patch("app.services.embedding_cache._save_embedding") as mock_save, \
         patch("app.services.embedding_cache.settings") as mock_s:
        mock_s.openai_client.embeddings.create = AsyncMock(
            return_value=MagicMock(data=[MagicMock(embedding=[0.1] * 3072)])
        )
        result = await get_embedding_async("테스트 질문")

    assert result == [0.1] * 3072
    mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_cache_hit_skips_openai():
    with patch("app.services.embedding_cache._get_cached_embedding", return_value=[0.2] * 3072), \
         patch("app.services.embedding_cache.settings") as mock_s:
        result = await get_embedding_async("테스트 질문")

    mock_s.openai_client.embeddings.create.assert_not_called()
    assert result == [0.2] * 3072


@pytest.mark.asyncio
async def test_openai_error_propagates():
    with patch("app.services.embedding_cache._get_cached_embedding", return_value=None), \
         patch("app.services.embedding_cache.settings") as mock_s:
        mock_s.openai_client.embeddings.create = AsyncMock(side_effect=Exception("API error"))
        with pytest.raises(Exception, match="API error"):
            await get_embedding_async("테스트 질문")
