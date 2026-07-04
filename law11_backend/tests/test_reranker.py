from unittest.mock import MagicMock, patch

from app.services.reranker import rerank


def test_rerank_returns_top_k_indices_by_score():
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.1, 0.9, 0.5, 0.3, 0.8, 0.2, 0.7, 0.4, 0.6, 0.0]
    with patch("app.services.reranker._get_model", return_value=mock_model):
        indices = rerank("질문", [f"조문{i}" for i in range(10)], top_k=5)
    assert indices == [1, 4, 6, 8, 2]


def test_rerank_model_load_failure_returns_original_order():
    with patch("app.services.reranker._get_model", return_value=None):
        indices = rerank("질문", ["a", "b", "c"], top_k=2)
    assert indices == [0, 1]


def test_rerank_fewer_docs_than_top_k_returns_all_ranked():
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.5, 0.9]
    with patch("app.services.reranker._get_model", return_value=mock_model):
        indices = rerank("질문", ["a", "b"], top_k=5)
    assert indices == [1, 0]


def test_rerank_single_doc_skips_model():
    mock_model = MagicMock()
    with patch("app.services.reranker._get_model", return_value=mock_model):
        indices = rerank("질문", ["단일 조문"], top_k=5)
    mock_model.predict.assert_not_called()
    assert indices == [0]


def test_rerank_predict_error_returns_original_order():
    mock_model = MagicMock()
    mock_model.predict.side_effect = RuntimeError("CUDA OOM")
    with patch("app.services.reranker._get_model", return_value=mock_model):
        indices = rerank("질문", ["a", "b", "c"], top_k=2)
    assert indices == [0, 1]
