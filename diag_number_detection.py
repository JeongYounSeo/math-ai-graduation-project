"""문제 번호 감지 진단 — 실제 PDF word 좌표를 뽑아 어느 필터에서 걸러지는지 보여준다.

사용법 (PowerShell, 프로젝트 루트에서):
    python diag_number_detection.py uploads/pdfs/PDF_B0A98A13.pdf
    python diag_number_detection.py uploads/pdfs/PDF_B0A98A13.pdf 1   # 특정 페이지만
"""
import sys, re

def main():
    if len(sys.argv) < 2:
        print("usage: python diag_number_detection.py <pdf_path> [page_no]")
        sys.exit(1)
    # PowerShell 등에서 인자 끝에 백슬래시/따옴표/공백이 딸려올 수 있어 정리한다.
    pdf_path = sys.argv[1].strip().strip("\\").strip('"').strip("'")
    only_page = None
    if len(sys.argv) > 2:
        raw = sys.argv[2].strip().strip("\\").strip('"').strip("'")
        if raw:
            try:
                only_page = int(raw)
            except ValueError:
                print(f"경고: page 인자 '{raw}' 를 숫자로 못 읽어 전체 페이지를 봅니다.")
                only_page = None

    import fitz
    doc = fitz.open(pdf_path)
    print(f"PDF: {pdf_path} | pages={len(doc)} | fitz={fitz.__version__}\n")

    for pno in range(len(doc)):
        if only_page is not None and pno + 1 != only_page:
            continue
        page = doc[pno]
        pw = page.rect.width
        ph = page.rect.height
        words = page.get_text("words")
        print(f"===== page {pno+1} | rect={pw:.0f}x{ph:.0f} | words={len(words)} =====")

        # "숫자." 형태 word 를 전부 뽑아서 각 필터 통과 여부 표시
        num_dot = []
        for w in words:
            if len(w) < 5:
                continue
            x0, y0, x1, y1, text, *_ = w
            cleaned = str(text).strip()
            if re.fullmatch(r"\d{1,2}\.", cleaned):
                num_dot.append((cleaned, x0, y0, x1, y1))

        if not num_dot:
            print("  '숫자.' 형태 word 없음 → 번호 감지 불가 (텍스트 레이어/인코딩 문제 가능)\n")
            continue

        print(f"  '숫자.' 형태 word {len(num_dot)}개:")
        for cleaned, x0, y0, x1, y1 in num_dot:
            n = int(cleaned[:-1])
            reasons = []
            if n < 1 or n > 30: reasons.append("범위밖(1~30)")
            if y0 < 50: reasons.append(f"y0<50(={y0:.0f})")
            if n >= 20 and (y0 > 700 or x0 > 500):
                reasons.append(f"n>=20&(y0>700 or x0>500) y0={y0:.0f},x0={x0:.0f}")
            verdict = "통과✓" if not reasons else "탈락✗ [" + ", ".join(reasons) + "]"
            print(f"    '{cleaned}' @({x0:.0f},{y0:.0f})  {verdict}")
        print()

    # ---- 전체 페이지 요약 (only_page 없을 때만) ----
    if only_page is None:
        print("\n" + "=" * 55)
        print("전체 페이지 요약 (감지된 문제번호)")
        print("=" * 55)
        total = 0
        for pno in range(len(doc)):
            page = doc[pno]
            pw = page.rect.width
            thr = pw / 2 if pw else 0
            words = page.get_text("words")
            nums = []
            for w in words:
                if len(w) < 5:
                    continue
                x0, y0, x1, y1, text, *_ = w
                cleaned = str(text).strip()
                if not re.fullmatch(r"\d{1,2}\.", cleaned):
                    continue
                n = int(cleaned[:-1])
                if n < 1 or n > 30 or y0 < 50:
                    continue
                if n >= 20 and (y0 > 700 or x0 > 500):
                    continue
                col = "L" if thr and x0 < thr else "R"
                nums.append((n, col))
            total += len(nums)
            disp = ", ".join(f"{n}({c})" for n, c in sorted(nums))
            print(f"  page {pno+1:2d}: {len(nums)}개  [{disp}]")
        print(f"\n  총 감지: {total}개 (DB problems 116개와 비교)")

    doc.close()

if __name__ == "__main__":
    main()
