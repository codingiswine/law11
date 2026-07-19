from app.tools.law_updater_async import extract_article_payloads, qdrant_point_id


def _drf(units):
    return {"법령": {"조문": {"조문단위": units}, "시행일자": "20260101"}}


def test_branch_article_norm_and_display():
    """가지조문 회귀 테스트: 조문가지번호를 무시하면 본조와 norm이 충돌해
    upsert가 본문을 덮어써 조문이 소실됨 (v1.6.0에서 수정, README #28)"""
    payloads = extract_article_payloads("재난및안전관리기본법", _drf([
        {"조문여부": "조문", "조문번호": "14", "조문내용": "제14조(중앙재난안전대책본부 등) 내용"},
        {"조문여부": "조문", "조문번호": "14", "조문가지번호": "2", "조문내용": "제14조의2(수습지원단 파견 등) 내용"},
    ]))
    norms = {p["article_number_norm"]: p["article_number"] for p in payloads}
    assert norms == {"14": "제14조", "14의2": "제14조의2"}


def test_deleted_article_skipped():
    """'제9조의2 삭제 <2013.8.6>' 같은 삭제 조문은 수집 제외"""
    payloads = extract_article_payloads("재난및안전관리기본법", _drf([
        {"조문여부": "조문", "조문번호": "9", "조문가지번호": "2", "조문내용": "제9조의2 삭제 <2013.8.6>"},
        {"조문여부": "조문", "조문번호": "10", "조문내용": "제10조(정상 조문) 내용"},
    ]))
    assert [p["article_number_norm"] for p in payloads] == ["10"]


def test_qdrant_point_id_deterministic():
    """point id는 (법령, 조문)에 대해 프로세스와 무관하게 항상 같아야
    upsert 중복/폐지 조문 삭제가 안전함 (v1.6.0에서 hash() → md5 교체)"""
    a = qdrant_point_id("산업안전보건법", "17")
    b = qdrant_point_id("산업안전보건법", "17")
    assert a == b
    assert qdrant_point_id("산업안전보건법", "17") != qdrant_point_id("산업안전보건법", "17의2")
    # 48비트 범위 (md5 hex 12자리) — Qdrant int id로 안전
    assert 0 <= a < 2 ** 48
