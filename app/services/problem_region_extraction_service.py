"""문제 이미지를 타입이 구분된 영역(region)으로 분해하는 오케스트레이션 서비스.

이 서비스는 순수 오케스트레이션만 담당한다. 네트워크·재시도·타임아웃·JSON 파싱
관심사는 전부 `ClaudeVisionClient`(주입 가능)에 캡슐화되어 있으므로, 테스트에서는
목(mock) vision_client를 주입하면 네트워크 없이 모든 경로를 결정적으로 재현할 수
있다(Req 15).

담당 범위(단일 파일에 함께 구현):
- 이미지 검증 + 자격증명 폴백 (Task 8.1)
- 단일 Vision 호출 + JSON 검증 + region_type 확정 + order_index 정렬 (Task 8.2)
- 텍스트 영역 OCR/LaTeX + confidence (Task 8.5)
- 다이어그램 크롭 + 바운딩 박스 클램프 (Task 8.8)
- 라벨 항목 구조화 (Task 8.11)
- 지문 재사용/생성 (Task 8.14)
- 조립 캐시 + 단일 단위 영속화 (Task 8.15)
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core import storage
from app.core.config import settings
from app.models.problem import Problem
from app.models.problem_region import ProblemRegion, RegionType
from app.models.problem_region_item import ProblemRegionItem
from app.prompts.region_extraction_prompt import build_region_extraction_prompt
from app.repositories.passage_repository import PassageRepository
from app.repositories.problem_region_item_repository import ProblemRegionItemRepository
from app.repositories.problem_region_repository import ProblemRegionRepository
from app.repositories.problem_repository import ProblemRepository
from app.services.claude_vision_client import (
    FAILURE_MALFORMED,
    ClaudeVisionClient,
    VisionCallResult,
)

logger = logging.getLogger(__name__)

# 텍스트 영역으로 취급되는 region_type 집합(OCR/LaTeX 대상). DIAGRAM은 제외한다.
_TEXT_REGION_TYPES = frozenset(
    {
        RegionType.QUESTION_TEXT.value,
        RegionType.CHOICE_BOX.value,
        RegionType.STATEMENT_BOX.value,
        RegionType.TABLE.value,
    }
)

# 라벨 항목(Labeled_Item)을 갖는 region_type 집합.
_LABELED_REGION_TYPES = frozenset(
    {RegionType.CHOICE_BOX.value, RegionType.STATEMENT_BOX.value}
)

# 유효한 region_type 값 집합. 여기에 없으면 OTHER로 강등한다(Req 1.4).
_VALID_REGION_TYPES = frozenset(rt.value for rt in RegionType)

# 영역당 허용 라벨 항목 수 상한(Req 4.1, 4.2).
_MAX_ITEMS_PER_REGION = 10

# 바운딩 박스가 없는 영역을 정렬 시 항상 마지막으로 보내기 위한 대체 정렬키.
_SORT_LAST = float("inf")


@dataclass
class RegionExtractionResult:
    """단일 문제에 대한 영역 추출 결과.

    - success: 전체 오케스트레이션 성공 여부
    - region_count: 실제로 생성·영속화된 영역 수
    - errors: 영역/항목 단위의 소프트 오류 표시(부분 실패를 담되 전체를 중단하지 않음)
    - fallback_used: 자격증명 부재로 스텁 폴백을 사용했는지 여부(Req 6.1)
    - failure_type: 하드 실패 유형("image_unreadable"|"malformed"|"timeout"|... )
    """

    success: bool
    region_count: int
    errors: List[str] = field(default_factory=list)
    fallback_used: bool = False
    failure_type: Optional[str] = None


# 메모리 상에서 영역 레코드를 조립하기 위한 중간 표현.
# DB에 넣기 전 정렬·검증·크롭을 마친 뒤 단일 단위로 영속화한다(Req 14.4).
@dataclass
class _PendingRegion:
    region_type: str
    bounding_box: Optional[dict]  # {left, top, right, bottom} 또는 None(무효)
    order_index: int
    ocr_text: Optional[str] = None
    latex_text: Optional[str] = None
    confidence: Optional[float] = None
    image_path: Optional[str] = None
    # 아직 크롭이 필요한 다이어그램인지 여부(영속화 후 크롭 저장).
    is_diagram: bool = False
    # 라벨 항목(있으면). 각 항목은 dict: {label, order_index, text, latex, image_path}
    items: List[dict] = field(default_factory=list)


class ProblemRegionExtractionService:
    """문제 이미지를 영역들로 분해하는 오케스트레이터.

    계층 규칙에 따라 리포지토리를 통해서만 영속화하며, `ProblemRegion` /
    `ProblemRegionItem` 테이블을 영역 콘텐츠의 원천(source of truth)으로 삼고
    기존 `problems.raw_text/raw_ocr_text/latex_text`는 파생 캐시로 갱신한다.
    """

    def __init__(self, db: Session, vision_client: Optional[ClaudeVisionClient] = None):
        self.db = db
        self.passage_repository = PassageRepository(db)
        self.region_repository = ProblemRegionRepository(db)
        self.item_repository = ProblemRegionItemRepository(db)
        self.problem_repository = ProblemRepository(db)
        # vision_client 미주입 시 설정값으로 기본 클라이언트 생성.
        self.vision_client = vision_client or ClaudeVisionClient(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.CLAUDE_VISION_MODEL,
        )

    # ------------------------------------------------------------------
    # 공개 진입점
    # ------------------------------------------------------------------
    def extract_regions(self, problem: Problem) -> RegionExtractionResult:
        """단일 문제에 대한 전체 추출 오케스트레이션.

        순서:
        1. 이미지 읽기 검증(Req 1.2) — Task 8.1
        2. 자격증명 없으면 스텁 폴백 + warning 로그 1회(Req 6.1, 6.4) — Task 8.1
        3. 단일 Vision 호출(Req 14.1) — Task 8.2
        4. JSON 구조 검증, malformed면 부분 저장 없이 실패(Req 14.5) — Task 8.2
        5. region_type 확정 + order_index 정렬(top→left)(Req 1.4~1.7) — Task 8.2
        6. 텍스트 영역 OCR/LaTeX(Req 2) — Task 8.5
        7. 라벨 항목 구조화(Req 4) — Task 8.11
        8. 지문 재사용/생성(Req 5) — Task 8.14
        9. 단일 단위 영속화 + 다이어그램 크롭(Req 3) + 조립 캐시(Req 11) — Task 8.8, 8.15
        """
        errors: List[str] = []

        # ---- Task 8.1: 이미지 검증 (Req 1.2) ----
        image_path = getattr(problem, "problem_image_path", None)
        if not self._is_readable_image(image_path):
            return RegionExtractionResult(
                success=False,
                region_count=0,
                errors=[f"이미지를 읽을 수 없습니다: {image_path}"],
                failure_type="image_unreadable",
            )

        # ---- Task 8.1: 자격증명 부재 시 스텁 폴백 (Req 6.1, 6.4) ----
        if not self.vision_client.is_configured():
            logger.warning(
                "Claude 자격증명을 찾을 수 없어 스텁 폴백으로 처리합니다: image=%s",
                image_path,
            )
            # 네트워크 호출 없이 성공 반환. 기존 problem 필드는 그대로 둔다.
            return RegionExtractionResult(
                success=True,
                region_count=0,
                errors=[],
                fallback_used=True,
            )

        # ---- Task 8.2: 단일 Vision 호출 (Req 14.1, 14.2) ----
        prompt = build_region_extraction_prompt()
        result: VisionCallResult = self.vision_client.extract(image_path, prompt)

        if not result.success:
            # malformed는 명시적 실패 메시지로 구분(Req 14.5).
            if result.failure_type == FAILURE_MALFORMED:
                logger.error("Vision 응답이 malformed입니다: image=%s", image_path)
                return RegionExtractionResult(
                    success=False,
                    region_count=0,
                    errors=["malformed extraction output"],
                    failure_type=FAILURE_MALFORMED,
                )
            # timeout/rate_limited/server_error/not_configured 등: 부분 저장 없이 실패.
            logger.warning(
                "Vision 호출 실패: type=%s image=%s",
                result.failure_type,
                image_path,
            )
            return RegionExtractionResult(
                success=False,
                region_count=0,
                errors=[result.error_message or "vision call failed"],
                failure_type=result.failure_type,
            )

        # ---- Task 8.2: JSON 구조 검증 (Req 14.5) ----
        raw_json = result.raw_json
        if not isinstance(raw_json, dict) or not isinstance(
            raw_json.get("regions"), list
        ):
            logger.error(
                "Vision 응답의 구조가 올바르지 않습니다(regions 배열 없음): image=%s",
                image_path,
            )
            return RegionExtractionResult(
                success=False,
                region_count=0,
                errors=["malformed extraction output"],
                failure_type=FAILURE_MALFORMED,
            )

        raw_regions = raw_json["regions"]

        # ---- Task 8.2: 빈 영역이면 성공(빈 컬렉션) (Req 1.8) ----
        # 단, 조립 캐시는 빈 값으로 갱신한다(Req 11.6). 아래 영속화 단계에서 처리.

        # ---- 좌표 복원용 이미지 크기 취득(2026-09-17): Vision 은 0~1 정규화 좌표로
        #      답하므로, 픽셀 복원을 위해 실제 문제 이미지 크기를 읽어 넘긴다.
        img_w, img_h = self._read_image_size(image_path)

        # ---- Task 8.2 + 8.5 + 8.11: 메모리 상에서 영역/항목 조립 ----
        pending_regions = self._build_pending_regions(
            raw_regions, errors, img_width=img_w, img_height=img_h
        )

        # ---- Task 8.14: 지문 재사용/생성 (Req 5) ----
        # 프롬프트가 별도 passage 객체를 내보내지 않을 수 있으므로 guard로 감싼다.
        passage_ok, passage_id = self._resolve_passage(problem, raw_json, errors)
        if not passage_ok:
            # 지문 OCR 실패: Passage 미저장, passage_id 미설정, 오류 반환(Req 5.5).
            # 이 시점까지 영역을 아직 영속화하지 않았으므로 부분 저장이 없다.
            return RegionExtractionResult(
                success=False,
                region_count=0,
                errors=errors,
                failure_type="passage_ocr_failed",
            )

        # ---- Task 8.8 + 8.15: 단일 단위 영속화 (Req 3, 11, 14.4) ----
        return self._persist_all(
            problem=problem,
            pending_regions=pending_regions,
            passage_id=passage_id,
            image_path=image_path,
            soft_errors=errors,
        )

    # ------------------------------------------------------------------
    # Task 8.1: 이미지 검증 헬퍼
    # ------------------------------------------------------------------
    @staticmethod
    def _read_image_size(image_path: Optional[str]):
        """문제 이미지의 (width, height) 를 반환한다. 실패 시 (None, None)."""
        if not image_path:
            return (None, None)
        try:
            from PIL import Image

            with Image.open(image_path) as img:
                return img.size  # (width, height)
        except Exception:
            return (None, None)

    @staticmethod
    def _is_readable_image(image_path: Optional[str]) -> bool:
        """PIL로 이미지를 열어 읽기 가능 여부를 검증한다(Req 1.2)."""
        if not image_path:
            return False
        try:
            from PIL import Image

            with Image.open(image_path) as img:
                img.verify()  # 손상 여부 검증(디코딩까지 강제하지 않음).
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Task 8.2 / 8.5 / 8.11: 메모리 상 영역 조립
    # ------------------------------------------------------------------
    def _build_pending_regions(
        self,
        raw_regions: list,
        errors: List[str],
        img_width=None,
        img_height=None,
    ) -> List[_PendingRegion]:
        """raw JSON 영역 배열을 정렬·타입확정·텍스트/항목 반영한 중간 표현으로 변환.

        정렬: 바운딩 박스 top 오름차순, 동일하면 left 오름차순. 유효 박스가 없는
        영역은 결정적으로 맨 뒤로 보낸다. 정렬 후 0-기반 연속 order_index를 부여한다
        (Req 1.6, 1.7).
        """
        parsed: List[_PendingRegion] = []

        for idx, raw in enumerate(raw_regions):
            if not isinstance(raw, dict):
                errors.append(f"region {idx}: 영역 객체 형식이 올바르지 않습니다")
                continue

            # ---- Task 8.2: region_type 확정 (Req 1.4) ----
            region_type = self._coerce_region_type(raw.get("region_type"))

            # ---- Task 8.2: 바운딩 박스 파싱 (Req 1.5) ----
            bbox = self._parse_bounding_box(
                raw.get("bounding_box"), img_width, img_height
            )
            if bbox is None:
                errors.append(f"region {idx}: 바운딩 박스가 유효하지 않습니다")

            pending = _PendingRegion(
                region_type=region_type,
                bounding_box=bbox,
                order_index=-1,  # 정렬 후 확정.
            )

            if region_type == RegionType.DIAGRAM.value:
                # ---- Task 8.8: 다이어그램은 OCR/LaTeX 생략, 크롭 대상 표시 (Req 3.1) ----
                pending.is_diagram = True
                pending.confidence = self._coerce_confidence(raw.get("confidence"))
            elif region_type in _TEXT_REGION_TYPES:
                # ---- Task 8.5: 텍스트 영역 OCR/LaTeX/confidence (Req 2) ----
                self._apply_text_fields(pending, raw, idx, errors)
                # ---- Task 8.11: 라벨 항목 (Req 4) ----
                if region_type in _LABELED_REGION_TYPES:
                    self._apply_labeled_items(pending, raw, idx, errors)
            else:
                # OTHER: confidence만 반영(텍스트/크롭 없음).
                pending.confidence = self._coerce_confidence(raw.get("confidence"))

            parsed.append(pending)

        # ---- Task 8.2: 정렬 + order_index 부여 (Req 1.6, 1.7) ----
        parsed.sort(key=self._region_sort_key)
        for order_index, pending in enumerate(parsed):
            pending.order_index = order_index

        return parsed

    @staticmethod
    def _coerce_region_type(value) -> str:
        """제공된 region_type이 유효하면 그대로, 아니면 OTHER로 강등한다(Req 1.4)."""
        if isinstance(value, str) and value in _VALID_REGION_TYPES:
            return value
        return RegionType.OTHER.value

    @staticmethod
    def _parse_bounding_box(raw_box, img_width=None, img_height=None) -> Optional[dict]:
        """bounding_box dict를 {left, top, right, bottom} 픽셀 float로 정규화한다.

        좌표 규약(2026-09-17):
        - Vision 은 0.0~1.0 정규화 비율 좌표로 답한다. img_width/img_height 가
          주어지고 네 값이 모두 <= 1.0 이면 이미지 크기를 곱해 픽셀로 복원한다.
        - 하나라도 > 1.0 이면 레거시 픽셀 좌표로 간주하고 그대로 둔다(하위호환).
        - img_width/img_height 가 없으면(테스트 등) 값을 그대로 통과시킨다.

        left<right, top<bottom을 만족하지 않거나 좌표가 숫자가 아니면 None.
        """
        if not isinstance(raw_box, dict):
            return None
        try:
            left = float(raw_box["left"])
            top = float(raw_box["top"])
            right = float(raw_box["right"])
            bottom = float(raw_box["bottom"])
        except (KeyError, TypeError, ValueError):
            return None
        if right <= left or bottom <= top:
            return None
        # 정규화 좌표(모든 값 <= 1.0)면 이미지 크기를 곱해 픽셀로 복원.
        if (
            img_width
            and img_height
            and max(left, top, right, bottom) <= 1.0
        ):
            left *= img_width
            right *= img_width
            top *= img_height
            bottom *= img_height
        return {"left": left, "top": top, "right": right, "bottom": bottom}

    @staticmethod
    def _coerce_confidence(value) -> Optional[float]:
        """confidence를 [0.0, 1.0]으로 클램프한다. 숫자가 아니면 None(Req 2.4, 2.5)."""
        if isinstance(value, bool):
            # bool은 int의 하위형이므로 명시적으로 배제한다.
            return None
        if not isinstance(value, (int, float)):
            return None
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _region_sort_key(pending: "_PendingRegion"):
        """정렬키: (top, left). 유효 박스가 없으면 (inf, inf)로 맨 뒤."""
        bbox = pending.bounding_box
        if bbox is None:
            return (_SORT_LAST, _SORT_LAST)
        return (bbox["top"], bbox["left"])

    # ------------------------------------------------------------------
    # Task 8.5: 텍스트 영역 반영
    # ------------------------------------------------------------------
    def _apply_text_fields(
        self,
        pending: "_PendingRegion",
        raw: dict,
        idx: int,
        errors: List[str],
    ) -> None:
        """텍스트 영역의 ocr_text/latex_text/confidence를 반영한다(Req 2.1~2.6).

        ocr_text가 비어있거나 없으면(추출 실패) ocr_text·latex_text를 null로 두고
        오류를 표시한 뒤 나머지 처리는 계속한다(Req 2.6).
        """
        pending.confidence = self._coerce_confidence(raw.get("confidence"))

        ocr_text = raw.get("ocr_text")
        if not isinstance(ocr_text, str) or not ocr_text.strip():
            # 텍스트 추출 실패/빈 결과: 두 필드 모두 null 유지, 오류 표시(Req 2.6).
            pending.ocr_text = None
            pending.latex_text = None
            errors.append(f"region {idx}: 텍스트 추출 실패")
            return

        pending.ocr_text = ocr_text

        # latex_text는 프롬프트가 이미 수식은 $...$로, 평문은 그대로 지시한다(Req 2.2, 2.3).
        latex_text = raw.get("latex_text")
        if isinstance(latex_text, str) and latex_text.strip():
            pending.latex_text = latex_text
        else:
            # latex_text가 비면 평문(ocr_text)을 그대로 둔다(수식 없음 케이스, Req 2.3).
            pending.latex_text = ocr_text

    # ------------------------------------------------------------------
    # Task 8.11: 라벨 항목 구조화
    # ------------------------------------------------------------------
    def _apply_labeled_items(
        self,
        pending: "_PendingRegion",
        raw: dict,
        idx: int,
        errors: List[str],
    ) -> None:
        """CHOICE_BOX/STATEMENT_BOX의 items 배열을 라벨 항목으로 구조화한다(Req 4).

        라벨은 원문 그대로 보존하고, 읽기 순서(주어진 순서)대로 0-기반 연속
        order_index를 부여한다. 항목이 없으면 오류만 표시하고 영역 자체는 보존한다
        (Req 4.7).
        """
        raw_items = raw.get("items")
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            errors.append(f"region {idx}: 라벨 항목 미검출")
            return

        # 상한 10개 초과 시 앞에서부터 10개만 취한다(Req 4.1, 4.2).
        usable = raw_items[:_MAX_ITEMS_PER_REGION]

        built: List[dict] = []
        for item_order, raw_item in enumerate(usable):
            if not isinstance(raw_item, dict):
                errors.append(
                    f"region {idx} item {item_order}: 항목 형식이 올바르지 않습니다"
                )
                continue

            label = raw_item.get("label")
            # 라벨은 원문 그대로 보존. 문자열이 아니면 문자열화하되 빈 값은 오류 표시.
            if label is None or (isinstance(label, str) and not label.strip()):
                errors.append(f"region {idx} item {item_order}: 라벨 누락")
                label_value = ""
            else:
                label_value = label if isinstance(label, str) else str(label)

            is_image = bool(raw_item.get("is_image"))

            if is_image:
                # ---- 이미지 항목: text/latex 비우고 image_path만(여기서는 None) (Req 4.6) ----
                text_value = None
                latex_value = None
            else:
                # ---- 텍스트 항목 (Req 4.4, 4.5) ----
                text = raw_item.get("text")
                text_value = text if isinstance(text, str) and text.strip() else None
                latex = raw_item.get("latex")
                latex_value = (
                    latex if isinstance(latex, str) and latex.strip() else None
                )

            built.append(
                {
                    "label": label_value,
                    "order_index": len(built),  # 0-기반 연속(형식 오류 항목 건너뜀 반영).
                    "text": text_value,
                    "latex": latex_value,
                    "image_path": None,
                }
            )

        if not built:
            # 모든 항목이 형식 오류였던 경우: 미검출과 동일 취급, 영역은 보존(Req 4.7).
            errors.append(f"region {idx}: 라벨 항목 미검출")
            return

        pending.items = built

    # ------------------------------------------------------------------
    # Task 8.14: 지문 재사용/생성
    # ------------------------------------------------------------------
    def _resolve_passage(
        self,
        problem: Problem,
        raw_json: dict,
        errors: List[str],
    ):
        """지문을 재사용하거나 생성하고 problem.passage_id에 반영할 값을 결정한다(Req 5).

        반환: (ok: bool, passage_id: Optional[int])
        - ok=False는 지문 OCR 실패(Req 5.5)로, 호출부가 부분 저장 없이 실패 반환한다.
        - passage 정보가 없으면 (True, 기존 problem.passage_id 유지)로 no-op.
        """
        passage = raw_json.get("passage")
        if not passage or not isinstance(passage, dict):
            # 프롬프트가 passage를 내보내지 않는 경우 등: no-op.
            return True, getattr(problem, "passage_id", None)

        crop_box = passage.get("crop_box")

        # ---- Req 5.1, 5.2: 기존 Passage 재사용 (find_matching은 5px 허용오차) ----
        existing = self.passage_repository.find_matching(
            source_pdf_id=self._passage_source_id(problem),
            page_number=getattr(problem, "page_number", None),
            crop_box=crop_box if isinstance(crop_box, dict) else {},
        )
        if existing is not None:
            # 기존 지문 참조, OCR 생략(Req 5.2).
            return True, existing.id

        # ---- Req 5.5: 신규 지문 OCR 실패 시 미저장 ----
        ocr_text = passage.get("ocr_text")
        if not isinstance(ocr_text, str) or not ocr_text.strip():
            errors.append("passage: 지문 OCR 실패로 Passage를 생성하지 않았습니다")
            return False, None

        # ---- Req 5.3: 신규 Passage 정확히 1건 생성 ----
        try:
            created = self.passage_repository.create(
                {
                    "source_pdf_id": self._passage_source_id(problem),
                    "page_number": getattr(problem, "page_number", None),
                    "passage_image_path": passage.get("image_path")
                    or passage.get("passage_image_path"),
                    "crop_box": crop_box if isinstance(crop_box, dict) else None,
                    "ocr_text": ocr_text,
                    "latex_text": passage.get("latex_text"),
                }
            )
        except Exception as exc:  # DB 제약 위반 등
            self.db.rollback()
            errors.append(f"passage: Passage 생성 실패: {exc}")
            return False, None

        return True, created.id

    @staticmethod
    def _passage_source_id(problem: Problem):
        """Passage.source_pdf_id는 정수 FK다. problem.source_pdf_id(String) 대신
        정수 변환이 가능하면 사용하고, 아니면 그대로 전달한다.

        find_matching은 필터에만 쓰이므로 값이 그대로 비교되면 충분하다.
        """
        return getattr(problem, "source_pdf_id", None)

    # ------------------------------------------------------------------
    # Task 8.8 + 8.15: 단일 단위 영속화 (다이어그램 크롭 + 조립 캐시)
    # ------------------------------------------------------------------
    def _persist_all(
        self,
        problem: Problem,
        pending_regions: List["_PendingRegion"],
        passage_id: Optional[int],
        image_path: str,
        soft_errors: List[str],
    ) -> RegionExtractionResult:
        """영역·항목·다이어그램 크롭·조립 캐시·passage_id를 단일 트랜잭션으로 영속화한다.

        - flush로 region id를 확보한 뒤 다이어그램 크롭을 저장하고 image_path를 갱신
          한다(Req 3.2, 3.3). 크롭 실패는 소프트 오류로 격리한다(Req 3.5, 3.6).
        - 항목을 삽입한다(Req 4).
        - 조립 캐시를 (order_index, region id)로 정렬해 채운다(Req 11.2, 11.4).
          영역이 없으면 빈 문자열로 채운다(Req 11.6).
        - commit 실패 시 rollback하여 부분 저장을 막는다(Req 11.5, 14.4).
        """
        # 실패 시 복원할 기존 캐시 값 백업(Req 11.5).
        prev_raw_text = getattr(problem, "raw_text", None)
        prev_raw_ocr_text = getattr(problem, "raw_ocr_text", None)
        prev_latex_text = getattr(problem, "latex_text", None)

        errors = list(soft_errors)

        try:
            created_regions: List[tuple] = []  # (ProblemRegion, _PendingRegion)

            # 1) 영역 삽입 후 flush로 id 확보(commit은 마지막에 1회).
            for pending in pending_regions:
                region = ProblemRegion(
                    problem_id=problem.id,
                    region_type=pending.region_type,
                    order_index=pending.order_index,
                    image_path=None,
                    bounding_box=pending.bounding_box or {},
                    ocr_text=pending.ocr_text,
                    latex_text=pending.latex_text,
                    confidence=pending.confidence,
                )
                self.db.add(region)
                created_regions.append((region, pending))

            self.db.flush()  # region.id 확보.

            # 2) 다이어그램 크롭 저장 + image_path 갱신(Req 3).
            for region, pending in created_regions:
                if pending.is_diagram:
                    self._crop_and_save_diagram(
                        problem=problem,
                        region=region,
                        bbox=pending.bounding_box,
                        image_path=image_path,
                        errors=errors,
                    )

            # 3) 라벨 항목 삽입(Req 4).
            for region, pending in created_regions:
                for item in pending.items:
                    self.db.add(
                        ProblemRegionItem(
                            region_id=region.id,
                            label=item["label"],
                            order_index=item["order_index"],
                            text=item["text"],
                            latex=item["latex"],
                            image_path=item["image_path"],
                        )
                    )

            # 4) 조립 캐시 갱신(Req 11.2, 11.4, 11.6).
            self._assemble_cache(problem, created_regions)

            # 5) passage_id 설정(Req 5.4).
            if passage_id is not None:
                problem.passage_id = passage_id

            self.db.add(problem)

            # 6) 단일 커밋(단일 단위 영속화, Req 14.4).
            self.db.commit()

        except Exception as exc:
            # 부분 저장 방지: rollback 후 기존 캐시 값 복원(Req 11.5, 14.4).
            self.db.rollback()
            problem.raw_text = prev_raw_text
            problem.raw_ocr_text = prev_raw_ocr_text
            problem.latex_text = prev_latex_text
            logger.error("영역 영속화 실패, 롤백함: image=%s error=%s", image_path, exc)
            return RegionExtractionResult(
                success=False,
                region_count=0,
                errors=errors + [f"영속화 실패: {exc}"],
                failure_type="persistence_failed",
            )

        return RegionExtractionResult(
            success=True,
            region_count=len(pending_regions),
            errors=errors,
        )

    def _crop_and_save_diagram(
        self,
        problem: Problem,
        region: ProblemRegion,
        bbox: Optional[dict],
        image_path: str,
        errors: List[str],
    ) -> None:
        """다이어그램 영역을 원본 이미지에서 크롭해 저장하고 image_path를 갱신한다.

        경계 클램프 후 무효 박스면 크롭을 생략하고 image_path를 비운다(Req 3.4, 3.5).
        저장 실패도 소프트 오류로 격리한다(Req 3.6).
        """
        if bbox is None:
            errors.append(f"region {region.order_index}: 다이어그램 바운딩 박스 무효")
            return

        try:
            from PIL import Image

            with Image.open(image_path) as img:
                img = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
                width, height = img.size

                # ---- Req 3.4: 경계로 클램프 ----
                left = max(0, int(bbox["left"]))
                top = max(0, int(bbox["top"]))
                right = min(width, int(bbox["right"]))
                bottom = min(height, int(bbox["bottom"]))

                # ---- Req 3.5: 클램프 후 무효(폭/높이 1px 미만, 면적 0 이하) ----
                if right - left < 1 or bottom - top < 1:
                    errors.append(
                        f"region {region.order_index}: 클램프 후 무효 바운딩 박스로 크롭 생략"
                    )
                    return

                crop = img.crop((left, top, right, bottom))

                # ---- Req 3.3 + Req 10: 경로 규칙에 따라 저장 ----
                target_path = storage.get_region_image_path(
                    problem.source_pdf_id, problem.id, region.id
                )
                crop.save(target_path)
                region.image_path = str(target_path)
        except Exception as exc:
            # ---- Req 3.6: 저장 실패 시 image_path 비우고 오류 표시, 계속 ----
            region.image_path = None
            errors.append(
                f"region {region.order_index}: 다이어그램 크롭 저장 실패: {exc}"
            )

    @staticmethod
    def _assemble_cache(problem: Problem, created_regions: List[tuple]) -> None:
        """(order_index, region id) 정렬로 영역 내용을 연결해 조립 캐시를 채운다(Req 11.2, 11.4).

        영역이 없으면 세 필드를 빈 문자열로 채운다(Req 11.6).
        """
        if not created_regions:
            problem.raw_text = ""
            problem.raw_ocr_text = ""
            problem.latex_text = ""
            return

        ordered = sorted(
            created_regions,
            key=lambda pair: (pair[0].order_index, pair[0].id),
        )

        ocr_parts = [
            region.ocr_text for region, _ in ordered if region.ocr_text is not None
        ]
        latex_parts = [
            region.latex_text for region, _ in ordered if region.latex_text is not None
        ]

        assembled_ocr = "\n".join(ocr_parts)
        assembled_latex = "\n".join(latex_parts)

        problem.raw_ocr_text = assembled_ocr
        problem.latex_text = assembled_latex
        # raw_text는 사람이 읽는 조립 결과로 ocr 조립본을 미러링한다(Req 11.2).
        problem.raw_text = assembled_ocr
