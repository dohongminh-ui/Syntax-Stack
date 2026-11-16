"""Canned hints for Code Rescue and Syntax Rows (always ``source: "canned"``).

AI feedback does not go through this module: ``app/tutor.py`` (``tutor.feedback``) is called
directly from ``app/main.py`` and falls back to the authored text produced here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class Hint:
    level: int
    text: str
    source: str = "canned"

    def as_dict(self) -> dict:
        return {"level": self.level, "text": self.text, "source": self.source}


class HintProvider(Protocol):
    def puzzle_hint(self, puzzle: dict, level: int) -> Hint:
        """``puzzle`` is the stored puzzle row (with ``hints`` as a list of 3 strings)."""

    def rows_hint(self, level_cfg: dict, level: int, error_group: Optional[str]) -> Hint:
        """``level_cfg`` is the loaded Syntax Rows level (hints / group_hints keys)."""


# Generic Syntax Rows fallbacks, used when a level file has no hints for an error group.
GENERIC_ROWS_HINTS: dict[str, list[str]] = {
    "syntax": [
        "Mỗi dòng mã phải viết đúng cú pháp Python.",
        "Đọc lại dòng bị tô đỏ: có mảnh nào thừa, thiếu hoặc nằm sai chỗ không?",
        "Thử bỏ bớt mảnh gây nhiễu và ghép lại dòng đó từ đầu theo đúng thứ tự các mảnh.",
    ],
    "bad_indent": [
        "Thụt lề cho Python biết dòng nào thuộc về khối lệnh nào.",
        "Dòng ngay sau một lệnh kết thúc bằng dấu hai chấm phải thụt vào một mức; các dòng khác thì không.",
        "Đặt mảnh đầu tiên của dòng thân khối vào cột thụt lề số 1, còn các dòng còn lại bắt đầu ở cột 0.",
    ],
    "missing_colon": [
        "Các lệnh như if, for, def kết thúc bằng dấu hai chấm.",
        "Nhìn dòng bị tô đỏ: lệnh mở khối phải có mảnh ':' ở cuối.",
        "Đặt mảnh ':' vào cuối dòng if / for / def, sau mảnh cuối cùng của dòng đó.",
    ],
    "wrong_order": [
        "Chương trình chạy từ trên xuống dưới, nên cái gì được dùng thì phải được tạo trước.",
        "Biến hoặc hàm phải được tạo ở dòng đứng trước dòng sử dụng nó.",
        "Kiểm tra lại thứ tự các hàng: đặt dòng tạo biến (hoặc def) lên trước dòng dùng nó.",
    ],
    "output_mismatch": [
        "Chương trình chạy được nhưng in ra khác với yêu cầu.",
        "So sánh đầu ra thực tế với đầu ra mong đợi để xem thiếu, thừa hay sai giá trị nào.",
        "Kiểm tra từng mảnh số và từng mảnh gây nhiễu: có mảnh nào cho giá trị gần đúng nhưng không đúng không?",
    ],
    "missing_construct": [
        "Màn này yêu cầu dùng một cấu trúc cụ thể của Python.",
        "Đầu ra đúng chưa đủ; chương trình còn phải dùng đúng cấu trúc mà đề bài muốn luyện.",
        "Xem lại các mảnh trong khay: mảnh từ khóa (for, if, def, return) nào chưa được dùng?",
    ],
    "empty": [
        "Hãy kéo các mảnh mã từ khay lên bàn chơi.",
        "Mỗi hàng của bàn chơi là một dòng lệnh; đặt các mảnh của một dòng vào cùng một hàng.",
        "Bắt đầu với dòng đầu tiên của chương trình, rồi nhấn Chạy kiểm tra.",
    ],
}


class CannedHintProvider:
    source = "canned"

    def puzzle_hint(self, puzzle: dict, level: int) -> Hint:
        hints = puzzle["hints"]
        return Hint(level, hints[level - 1], self.source)

    def rows_hint(self, level_cfg: dict, level: int, error_group: Optional[str]) -> Hint:
        if error_group:
            group_hints = (level_cfg.get("group_hints") or {}).get(error_group)
            if not group_hints:
                group_hints = GENERIC_ROWS_HINTS.get(error_group)
            if group_hints:
                return Hint(level, group_hints[level - 1], self.source)
        return Hint(level, level_cfg["hints"][level - 1], self.source)


_provider: HintProvider = CannedHintProvider()


def puzzle_hint(puzzle: dict, level: int) -> dict:
    return _provider.puzzle_hint(puzzle, level).as_dict()


def rows_hint(level_cfg: dict, level: int, error_group: Optional[str]) -> dict:
    return _provider.rows_hint(level_cfg, level, error_group).as_dict()
