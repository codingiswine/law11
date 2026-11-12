"""운영·설정 위생 (#90) — 사람이 기억하던 규칙을 테스트로.

(1) 코드가 읽는 환경변수는 전부 .env.example에 적혀 있어야 한다 (주석 처리된 `# KEY=`도 인정).
(2) init.sql에 특정 DB 역할 이름을 하드코딩한 GRANT가 없어야 한다 — DB_USER를 바꾸면 initdb가 깨졌다.
(3) qa_logger는 confidence_score 0.0을 null로 바꾸지 않는다.
(4) 파일 로그는 자정 회전 핸들러를 쓰고, 임포트 시점 날짜 폴더에 고정되지 않는다.
(5) 문서가 가리키는 eval 의존성 파일은 실제로 존재하는 경로여야 한다 (두 벌 중 옛것을 가리키고 있었다).
"""
import json
import re
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.services import qa_logger
import core.logger as core_logger

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent


def test_every_env_key_the_code_reads_is_documented_in_env_example():
    read = set()
    for py in list((_BACKEND / "app").rglob("*.py")) + list((_BACKEND / "core").rglob("*.py")):
        read |= set(re.findall(r"os\.(?:getenv|environ\.get)\(\s*['\"]([A-Z_][A-Z0-9_]*)", py.read_text(encoding="utf-8")))
    documented = set(re.findall(r"^\s*#?\s*([A-Z_][A-Z0-9_]*)=", (_BACKEND / ".env.example").read_text(encoding="utf-8"), re.M))
    missing = sorted(read - documented)
    assert not missing, f".env.example에 없는 환경변수: {missing}"


def test_init_sql_has_no_hardcoded_role_grant():
    sql = (_BACKEND / "init.sql").read_text(encoding="utf-8")
    grants = [ln.strip() for ln in sql.splitlines() if re.match(r"\s*GRANT\b", ln)]
    assert not grants, f"initdb는 DB_USER로 실행돼 소유권이 이미 있다 — 역할 하드코딩 GRANT 제거: {grants}"


def test_qa_logger_keeps_a_zero_confidence_score(tmp_path, monkeypatch):
    monkeypatch.setattr(qa_logger, "LOG_DIR", tmp_path)
    qa_logger.log_request(query="q", query_type="semantic", selected_source="qdrant",
                          selected_articles=[], fallback_used=False, confidence_score=0.0)
    entry = json.loads(next(tmp_path.glob("qa_*.jsonl")).read_text(encoding="utf-8").splitlines()[-1])
    assert entry["confidence_score"] == 0.0, "0.0이 null로 기록됐다 — 0점과 '점수 없음'은 다르다"


def test_file_logs_rotate_at_midnight_not_by_import_date():
    handlers = [h for h in (core_logger.chat_handler, core_logger.server_handler, core_logger.error_handler)]
    for h in handlers:
        assert isinstance(h, TimedRotatingFileHandler) and h.when == "MIDNIGHT", type(h)
        # logs/2026-11-12/server.log 처럼 날짜 폴더 아래에 고정돼 있으면 장기 실행 시 날짜가 멈춘다
        assert not re.search(r"\d{4}-\d{2}-\d{2}", Path(h.baseFilename).parent.name), h.baseFilename


def test_docs_point_at_an_eval_requirements_file_that_exists():
    bad = []
    for doc in ("README.md", "README.en.md", "docs/eval.md", "docs/roadmap.md", "CLAUDE.md", "law11_backend/README.md"):
        text = (_ROOT / doc).read_text(encoding="utf-8")
        for m in re.finditer(r"([\w./-]*requirements-eval\.txt)", text):
            rel = m.group(1)
            # 문서는 저장소 루트 기준(law11_backend/…)으로도, 백엔드 기준(requirements-eval.txt)으로도 적는다
            if not ((_ROOT / rel).exists() or (_BACKEND / rel).exists()):
                bad.append(f"{doc}: {rel}")
    assert not bad, "존재하지 않는 eval 의존성 파일을 가리킨다:\n  " + "\n  ".join(bad)
