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


def test_revision_metadata_not_in_text():
    """개정 메타데이터 혼입 회귀 테스트 (2026-11-03 실측).

    DRF는 개정된 항마다 "항제개정유형"("개정"/"신설")과 "항제개정일자문자열"
    ("2026.10.27")을 따로 내려준다. deep_extract_text가 모든 문자열을 긁는 탓에
    이 둘이 본문에 단독 줄로 섞여 들어갔다. "항내용" 끝에 이미 "<개정 2026.10.27>"
    태그가 있으므로 중복이다. 호가지번호("2")도 "호내용"의 "3의2."와 중복이었다.
    개정 이력이 있는 조문에만 나타나 1,641개 중 22개에서만 드러났다.
    """
    payloads = extract_article_payloads("산업안전보건법", _drf([{
        "조문여부": "조문",
        "조문번호": "52",
        "조문내용": "제52조(근로자의 작업중지)",
        "항": [
            {
                "항제개정유형": "개정",
                "항번호": "①",
                "항내용": "① 근로자는 작업을 중지하고 대피할 수 있다. <개정 2026.10.27>",
                "항제개정일자문자열": "2026.10.27",
            },
            {
                "항번호": "②",
                "항내용": "② 보고하여야 한다.",
                "호": [{"호번호": "3.", "호가지번호": "2", "호내용": "3의2. 대통령령으로 정하는 사업장"}],
            },
        ],
    }]))
    assert len(payloads) == 1
    lines = [ln.strip() for ln in payloads[0]["text"].splitlines() if ln.strip()]

    # 메타데이터가 단독 줄로 남아 있으면 안 된다
    assert "개정" not in lines, lines
    assert "신설" not in lines
    assert "2026.10.27" not in lines, lines
    assert "2" not in lines, lines

    # 본문은 그대로 보존 — 항내용 안의 <개정 ...> 태그는 원문이므로 유지된다
    assert any("근로자는 작업을 중지하고" in ln for ln in lines)
    assert any("3의2. 대통령령으로 정하는 사업장" in ln for ln in lines)
    assert "<개정 2026.10.27>" in payloads[0]["text"]
