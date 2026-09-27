"""OCR 결과(result dict)를 문제에 반영하는 얇은 apply 서비스 (설계 §5).

이 서비스는 **없는 OCR 파이프라인 전체를 새로 만들지 않고**, 이미 존재하는
result dict 를 입력으로 받아 두 가지 후처리만 수행한다:

1. 객관식(`answer_type == "multiple_choice"` & `choices` 존재)이면
   ``ProblemChoiceRepository.replace_choices_for_problem`` 로 보기를 재생성한다.
2. `full_problem` region 이 하나도 없을 때만, `crop_box`(xywh)를
   ``box_geometry.xywh_to_corner`` 로 corner 변환해 자동 생성한다.

설계 §5-4 (정답 추측 금지): ``correct_answer`` 가 주어져도 ``is_correct`` 를
자동 설정하지 않는다. ``replace_choices_for_problem`` 이 is_correct 를 전부
None 으로 유지하므로 이 규칙이 보장된다.

**스키마 갱신(2026-09-17)**: 설계 §5-1 의 "Problem.choices 저장"을 반영하여
Problem 모델에 ``choices``(JSON)/``answer_type``(String) 컬럼을 추가했다.
``ProblemChoiceRepository.replace_choices_for_problem`` 이 ProblemChoice 를
재생성할 때 이 두 컬럼도 같은 트랜잭션에서 동시 갱신한다(비정규화 사본; 정본은
ProblemChoice). ``correct_answer`` 는 여전히 저장하지 않는다(정답 추측 금지).

**연결 상태(2026-09-17 갱신)**: 이 서비스는 이제 자동 파이프라인에 연결돼 있다.
PDFImportService.import_pdf 가 region 추출(훅 2) 직후
``_build_ocr_result_from_regions`` 로 result dict 를 조립해 이 서비스를 호출하며,
``POST /{problem_id}/apply-ocr`` 엔드포인트로도 외부 result dict 를 직접 주입할 수
있다. Vision 미연동(스텁) 시에는 choices 가 비어 보기 저장은 skip 되고 full_problem
region 만 생성된다(회귀 0).
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.problem import Problem
from app.models.problem_region import ProblemRegion, RegionType
from app.repositories.problem_choice_repository import ProblemChoiceRepository
from app.repositories.problem_region_repository import ProblemRegionRepository
from app.utils.box_geometry import xywh_to_corner

logger = logging.getLogger(__name__)


class ProblemOcrApplyService:
    """OCR result dict 를 문제에 반영하는 서비스 (Service → Repository → Model)."""

    def __init__(self, db: Session):
        self.db = db
        self.choice_repo = ProblemChoiceRepository(db)
        self.region_repo = ProblemRegionRepository(db)

    def apply_ocr_result(self, problem_id: int, result: dict) -> dict:
        """OCR 결과를 반영하고 수행 요약 dict 를 반환한다.

        Args:
            problem_id: 대상 문제 id.
            result: OCR 결과 dict. 다음 키를 선택적으로 가질 수 있다(없으면 무시):
                - ``answer_type``: 예 "multiple_choice".
                - ``choices``: list[str] (객관식 보기 텍스트).
                - ``correct_answer``: Optional. 있어도 정답 자동 설정 안 함(추측 금지).
                - ``crop_box``: Optional xywh dict. 없으면 ``Problem.crop_box`` 사용.
                - ``page_width`` / ``page_height``: Optional 페이지 크기.

        Returns:
            ``{"choices_replaced": int, "full_problem_region_created": bool}``.
        """
        summary = {"choices_replaced": 0, "full_problem_region_created": False}

        if not isinstance(result, dict):
            logger.warning(
                "apply_ocr_result: result 가 dict 가 아니어서 무시합니다 (problem_id=%s)",
                problem_id,
            )
            return summary

        problem = self.db.query(Problem).filter(Problem.id == problem_id).first()
        if problem is None:
            # 방어적: 대상 문제가 없으면 아무것도 하지 않고 빈 요약 반환.
            logger.warning(
                "apply_ocr_result: problem_id=%s 를 찾을 수 없어 건너뜁니다", problem_id
            )
            return summary

        # 1) 객관식 보기 저장 --------------------------------------------------
        summary["choices_replaced"] = self._apply_choices(problem_id, result)

        # 2) full_problem region 자동 생성(없을 때만) --------------------------
        summary["full_problem_region_created"] = self._ensure_full_problem_region(
            problem, result
        )

        return summary

    # ------------------------------------------------------------------ #
    # 내부 헬퍼
    # ------------------------------------------------------------------ #
    def _apply_choices(self, problem_id: int, result: dict) -> int:
        """객관식이면 보기를 replace 하고 생성 개수를 반환한다. 아니면 0."""
        answer_type = result.get("answer_type")
        choices = result.get("choices")

        if answer_type != "multiple_choice":
            return 0
        if not isinstance(choices, list) or len(choices) == 0:
            return 0

        # 정답 추측 금지(설계 §5-4): correct_answer 가 있어도 is_correct 자동 설정
        # 하지 않는다. replace_choices_for_problem 이 is_correct 를 전부 None 으로
        # 유지하므로 규칙이 보장된다.
        # TODO(실제 OCR 연동 시): 신뢰 가능한 정답이 확정되면 별도 경로로
        #   is_correct 를 명시 반영한다. 이번 범위 밖.
        created = self.choice_repo.replace_choices_for_problem(problem_id, choices)
        return len(created)

    def _ensure_full_problem_region(self, problem: Problem, result: dict) -> bool:
        """full_problem region 이 없을 때만 crop_box 로 자동 생성한다.

        생성했으면 True, 이미 존재하거나 crop_box 가 무효/없으면 False.
        """
        existing = self.region_repo.get_by_problem_id(problem.id)
        has_full_problem = any(
            r.region_type == RegionType.FULL_PROBLEM.value for r in existing
        )
        if has_full_problem:
            return False

        crop_box = result.get("crop_box")
        if not self._is_valid_xywh(crop_box):
            crop_box = problem.crop_box

        if not self._is_valid_xywh(crop_box):
            # crop_box 가 없거나 무효 → 예외 던지지 않고 생성 생략(경고 1회).
            logger.warning(
                "apply_ocr_result: crop_box 가 없거나 무효라 full_problem region "
                "생성을 생략합니다 (problem_id=%s)",
                problem.id,
            )
            return False

        corner = xywh_to_corner(crop_box)

        page_width = result.get("page_width")
        page_height = result.get("page_height")

        # ProblemRegion 인스턴스를 먼저 만들어 set_box 로 corner + bounding_box 를
        # 동시에 기록한 뒤, 완성된 dict 를 repository.create 로 저장한다.
        # (bounding_box 컬럼이 nullable=False 이므로 create 전에 채워야 한다.)
        # 기존 region 이 없을 때만 생성하므로 order_index = 0.
        staged = ProblemRegion(
            problem_id=problem.id,
            region_type=RegionType.FULL_PROBLEM.value,
            order_index=0,
        )
        staged.set_box(corner, page_width, page_height)

        region_data = {
            "problem_id": problem.id,
            "region_type": RegionType.FULL_PROBLEM.value,
            "order_index": 0,
            "bounding_box": staged.bounding_box,
            "x1": staged.x1,
            "y1": staged.y1,
            "x2": staged.x2,
            "y2": staged.y2,
            "page_width": staged.page_width,
            "page_height": staged.page_height,
        }
        self.region_repo.create(region_data)
        return True

    @staticmethod
    def _is_valid_xywh(box: Optional[dict]) -> bool:
        """xywh dict 유효성: x,y,width,height 키가 있고 width>0, height>0."""
        if not isinstance(box, dict):
            return False
        required = {"x", "y", "width", "height"}
        if not required <= set(box):
            return False
        try:
            return float(box["width"]) > 0 and float(box["height"]) > 0
        except (TypeError, ValueError):
            return False
