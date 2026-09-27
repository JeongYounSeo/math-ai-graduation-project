def build_region_extraction_prompt() -> str:
    """단일 구조화 JSON 출력을 지시하는 Claude Vision 프롬프트를 반환한다.

    한 개의 수능 수학 문제 이미지를 타입이 구분된 영역(region)들로 분해하고,
    각 영역의 OCR/LaTeX 텍스트와 라벨 항목을 단일 구조화 JSON으로 반환하도록
    지시한다(Req 14.1, 14.3). DIAGRAM 영역은 OCR/LaTeX를 수행하지 않는다.
    """
    return """
당신은 한국 수능(대학수학능력시험) 수학 문제 이미지를 분석하는 비전 분석기입니다.
주어진 문제 이미지 하나를 타입이 구분된 영역(region)들의 집합으로 분해하고,
아래 규격을 정확히 따르는 **단일 JSON 객체 하나만** 출력하시오.

규칙:
1. 오직 하나의 JSON 객체만 출력하고, JSON 앞뒤에 설명 문장이나 마크다운 코드펜스(```)를 붙이지 마시오.
2. 최상위 객체는 "regions" 배열 하나를 포함한다.
3. 각 region 객체의 필드:
   - "region_type": 다음 중 정확히 하나
     - "QUESTION_TEXT": 문제 발문/지시문 텍스트
     - "DIAGRAM": 그림·그래프·도형 등 다이어그램(이미지)
     - "CHOICE_BOX": ①~⑤ 선택지 묶음
     - "STATEMENT_BOX": <보기> 등 ㄱ/ㄴ/ㄷ 항목 묶음
     - "TABLE": 표
     - "OTHER": 위에 해당하지 않는 영역
   - "bounding_box": {"left": <float>, "top": <float>, "right": <float>, "bottom": <float>}
     이미지 좌상단(0.0, 0.0)~우하단(1.0, 1.0) 기준 **정규화 비율 좌표**.
     반드시 0.0 이상 1.0 이하의 소수로 답하시오(절대 픽셀값 금지).
     예: 이미지 왼쪽 절반의 상단이면 left=0.0, right=0.5, top=0.0, bottom≈0.1.
     left<right, top<bottom.
   - "ocr_text": 영역에서 인식한 평문 텍스트(문자열). DIAGRAM이면 반드시 null.
   - "latex_text": 텍스트에 수식이 있으면 수식 부분을 $...$로 감싼 혼합 텍스트(문자열).
     수식이 없으면 평문 그대로. DIAGRAM이면 반드시 null.
   - "confidence": 인식 신뢰도. 0.0 이상 1.0 이하의 실수 또는 null.
   - "items": region_type이 "CHOICE_BOX" 또는 "STATEMENT_BOX"인 경우에만 라벨 항목 배열을 포함한다.
     그 외 타입에서는 이 필드를 생략하거나 null로 둔다.

4. DIAGRAM 영역은 절대 OCR/LaTeX를 수행하지 말고 "ocr_text"와 "latex_text"를 모두 null로 두시오.

5. "items" 배열의 각 항목 객체의 필드:
   - "label": 원문에 나타난 라벨 문자열 그대로. 예: "①", "②", "③", "④", "⑤" 또는 "ㄱ", "ㄴ", "ㄷ".
   - "text": 항목의 평문 텍스트(문자열). 항목이 이미지이면 null.
   - "latex": 항목에 수식이 있으면 $...$로 감싼 혼합 텍스트(문자열). 수식이 없거나 이미지 항목이면 null.
   - "is_image": 항목이 그림/도형 등 이미지이면 true, 텍스트이면 false (불리언).

6. 영역과 항목은 읽기 순서(위→아래, 같으면 왼쪽→오른쪽)에 가깝게 나열하시오.

출력 예시(스켈레톤):
{
  "regions": [
    {
      "region_type": "QUESTION_TEXT",
      "bounding_box": {"left": 0.05, "top": 0.05, "right": 0.95, "bottom": 0.20},
      "ocr_text": "함수 f(x)가 다음 조건을 만족시킬 때, f(2)의 값을 구하시오.",
      "latex_text": "함수 $f(x)$가 다음 조건을 만족시킬 때, $f(2)$의 값을 구하시오.",
      "confidence": 0.94,
      "items": null
    },
    {
      "region_type": "DIAGRAM",
      "bounding_box": {"left": 0.31, "top": 0.22, "right": 0.69, "bottom": 0.60},
      "ocr_text": null,
      "latex_text": null,
      "confidence": 0.88,
      "items": null
    },
    {
      "region_type": "STATEMENT_BOX",
      "bounding_box": {"left": 0.05, "top": 0.62, "right": 0.95, "bottom": 0.78},
      "ocr_text": "ㄱ. a>0 ㄴ. b=1 ㄷ. a+b>2",
      "latex_text": "ㄱ. $a>0$ ㄴ. $b=1$ ㄷ. $a+b>2$",
      "confidence": 0.9,
      "items": [
        {"label": "ㄱ", "text": "a>0", "latex": "$a>0$", "is_image": false},
        {"label": "ㄴ", "text": "b=1", "latex": "$b=1$", "is_image": false},
        {"label": "ㄷ", "text": "a+b>2", "latex": "$a+b>2$", "is_image": false}
      ]
    },
    {
      "region_type": "CHOICE_BOX",
      "bounding_box": {"left": 0.05, "top": 0.80, "right": 0.95, "bottom": 1.00},
      "ocr_text": "① 1 ② 2 ③ 3 ④ 4 ⑤ 5",
      "latex_text": "① $1$ ② $2$ ③ $3$ ④ $4$ ⑤ $5$",
      "confidence": 0.92,
      "items": [
        {"label": "①", "text": "1", "latex": "$1$", "is_image": false},
        {"label": "②", "text": "2", "latex": "$2$", "is_image": false},
        {"label": "③", "text": "3", "latex": "$3$", "is_image": false},
        {"label": "④", "text": "4", "latex": "$4$", "is_image": false},
        {"label": "⑤", "text": "5", "latex": "$5$", "is_image": false}
      ]
    }
  ]
}
"""
