"""daily/ 폴더의 기술 노트를 README.md의 발행 순서 그대로 읽어오는 유틸리티.

사용 예 (하루치 2개씩, 웹훅은 각각 따로 보낼 목적):
    from daily_notes import get_next_day_notes

    pair = get_next_day_notes()
    if pair is not None:
        chapter1_content = pair.first.content if pair.first else None
        chapter2_content = pair.second.content if pair.second else None
        # 이후 chapter1_content, chapter2_content를 각각 따로 웹훅으로 전송

한 개씩 가져오고 싶으면 get_next_note()를 대신 쓴다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
STATE_PATH = Path(__file__).resolve().parent / ".daily_notes_state.json"

_ROW_RE = re.compile(
    r"^\|\s*(?P<day>\d+)\s*\|\s*\[(?P<title>[^\]]+)\]\((?P<path>daily/[^)]+\.md)\)\s*\|\s*(?P<summary>.+?)\s*\|\s*$"
)


@dataclass
class DailyNote:
    day: int
    title: str
    summary: str
    path: Path  # 저장소 루트 기준 상대경로 (예: daily/day06-dto-vs-entity.md)
    content: str  # 마크다운 원문. list_daily_notes() 단계에서는 빈 문자열이고,
    # load_content() 또는 get_next_note()를 거쳐야 채워진다.


def list_daily_notes(readme_path: Path = README_PATH) -> list[DailyNote]:
    """README.md의 '## Daily' 표를 위에서 아래 순서 그대로 파싱해 목록으로 반환한다."""
    text = readme_path.read_text(encoding="utf-8")
    try:
        table_text = text.split("## Daily", 1)[1]
    except IndexError:
        raise ValueError("README.md에서 '## Daily' 섹션을 찾을 수 없습니다.")

    notes: list[DailyNote] = []
    for line in table_text.splitlines():
        match = _ROW_RE.match(line.strip())
        if not match:
            continue
        notes.append(
            DailyNote(
                day=int(match.group("day")),
                title=match.group("title"),
                summary=match.group("summary"),
                path=Path(match.group("path")),
                content="",
            )
        )
    return notes


def load_content(note: DailyNote, repo_root: Path = REPO_ROOT) -> str:
    """해당 노트 파일을 열어 마크다운 원문을 그대로(가공 없이) 반환한다."""
    full_path = repo_root / note.path
    return full_path.read_text(encoding="utf-8")


def _read_last_index() -> int:
    if not STATE_PATH.exists():
        return -1
    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return data.get("last_index", -1)


def _write_last_index(index: int) -> None:
    STATE_PATH.write_text(json.dumps({"last_index": index}), encoding="utf-8")


def get_next_note() -> Optional[DailyNote]:
    """아직 내보내지 않은 다음 글 하나를 순서대로 가져온다.

    실행할 때마다 커서(.daily_notes_state.json)가 한 칸씩 전진하므로,
    스크립트를 반복 실행해도 이미 가져간 글을 다시 반환하지 않는다.
    더 가져올 글이 없으면 None을 반환한다.
    """
    notes = list_daily_notes()
    next_index = _read_last_index() + 1

    if next_index >= len(notes):
        return None

    note = notes[next_index]
    note.content = load_content(note)  # 마크다운 원문이 그대로 이 변수에 저장된다
    _write_last_index(next_index)
    return note


@dataclass
class DailyPair:
    day: int
    first: Optional[DailyNote]  # 그날의 챕터 1
    second: Optional[DailyNote]  # 그날의 챕터 2 (없으면 None)


def get_next_day_notes() -> Optional[DailyPair]:
    """아직 내보내지 않은 다음 '하루치'(챕터 2개)를 한 번에 가져온다.

    `first`, `second` 각각이 독립된 DailyNote이고 원문도 `first.content`,
    `second.content`로 서로 다른 변수에 담기므로, 웹훅을 각각 따로 보낼 때
    그대로 나눠 쓰면 된다. 같은 일차가 아니면(데이터가 깨져 짝이 안 맞으면)
    `second`는 None이 되고, 다음 호출 때 그 글이 새 짝의 `first`로 나온다.
    더 가져올 글이 없으면 None을 반환한다.
    """
    notes = list_daily_notes()
    start_index = _read_last_index() + 1

    if start_index >= len(notes):
        return None

    first_note = notes[start_index]
    first_note.content = load_content(first_note)
    advanced_index = start_index

    second_note: Optional[DailyNote] = None
    has_pair = start_index + 1 < len(notes) and notes[start_index + 1].day == first_note.day
    if has_pair:
        second_note = notes[start_index + 1]
        second_note.content = load_content(second_note)
        advanced_index = start_index + 1

    _write_last_index(advanced_index)
    return DailyPair(day=first_note.day, first=first_note, second=second_note)


if __name__ == "__main__":
    pair = get_next_day_notes()

    if pair is None:
        print("더 가져올 글이 없습니다.")
    else:
        # 웹훅을 각각 따로 보낼 때 쓸 두 변수
        chapter1_content = pair.first.content if pair.first else None
        chapter2_content = pair.second.content if pair.second else None

        print(f"[{pair.day}일차]")
        print(f"챕터1: {pair.first.title} ({pair.first.path})")
        print(f"  글자 수: {len(chapter1_content)}")
        if pair.second:
            print(f"챕터2: {pair.second.title} ({pair.second.path})")
            print(f"  글자 수: {len(chapter2_content)}")
        else:
            print("챕터2: 없음 (이 일차엔 글이 1개뿐)")
