"""번호 기반 crop 미리보기 — DB 를 건드리지 않고, 원본 PDF 를 렌더해
새 번호 기반 분할이 어떻게 자르는지 절취선을 그려 저장한다.

사용법 (프로젝트 루트, PyMuPDF 필요):
    python preview_number_crop.py uploads/pdfs/PDF_B0A98A13.pdf
    python preview_number_crop.py uploads/pdfs/PDF_B0A98A13.pdf 1   # 특정 페이지

출력: preview_crop_page_XXX.png (페이지 이미지 + 번호기반 crop 절취선 + problem_number 라벨)
"""
import sys, os

def main():
    if len(sys.argv) < 2:
        print("usage: python preview_number_crop.py <pdf_path> [page_no]")
        sys.exit(1)
    pdf_path = sys.argv[1].strip().strip("\\").strip('"').strip("'")
    only_page = None
    if len(sys.argv) > 2:
        raw = sys.argv[2].strip().strip("\\").strip('"').strip("'")
        if raw:
            try:
                only_page = int(raw)
            except ValueError:
                pass

    import fitz
    from PIL import Image, ImageDraw
    from app.services.problem_crop_service import _crop_by_problem_numbers, RENDER_ZOOM

    doc = fitz.open(pdf_path)
    print(f"PDF: {pdf_path} | pages={len(doc)} | zoom={RENDER_ZOOM}")

    for pno in range(len(doc)):
        if only_page is not None and pno + 1 != only_page:
            continue
        page = doc[pno]
        # 렌더(파이프라인과 동일 zoom)
        pix = page.get_pixmap(matrix=fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM))
        tmp = f"_tmp_preview_page_{pno+1:03d}.png"
        pix.save(tmp)
        img = Image.open(tmp).convert("RGB")
        W, H = img.size

        cands = _crop_by_problem_numbers(tmp, pno + 1, W, H, page)
        draw = ImageDraw.Draw(img)
        if not cands:
            print(f"  page {pno+1}: 번호 기반 crop 없음(번호<2개) → 폴백 예정")
        else:
            colors = ["#e6194B", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4"]
            print(f"  page {pno+1}: {len(cands)}개 crop")
            for i, c in enumerate(cands):
                b = c.crop_box
                col = colors[i % len(colors)]
                x0, y0, x1, y1 = b["x"], b["y"], b["x"]+b["width"], b["y"]+b["height"]
                for off in range(4):
                    draw.rectangle([x0+off, y0+off, x1-off, y1-off], outline=col)
                lab = f"#{c.problem_number}"
                draw.rectangle([x0+4, y0+4, x0+4+len(lab)*11+8, y0+30], fill=col)
                draw.text((x0+8, y0+8), lab, fill="white")
                print(f"    문제{c.problem_number}: x={b['x']} y={b['y']} w={b['width']} h={b['height']}")

        out = f"preview_crop_page_{pno+1:03d}.png"
        # 보기 좋게 폭 900 으로 축소
        scale = 900 / W
        resized = img.resize((900, int(H * scale)))
        try:
            resized.save(out)
            print(f"    -> {out}")
        except OSError as e:
            # 파일이 뷰어에 열려 잠겼거나(Windows Errno 22) 경로 문제면 대체 이름으로 저장.
            import time
            alt = f"preview_crop_page_{pno+1:03d}_{int(time.time())}.png"
            try:
                resized.save(alt)
                print(f"    -> {alt} (원래 파일 저장 실패: {e}. 기존 파일이 열려있나 확인)")
            except OSError as e2:
                print(f"    !! 저장 실패: {e2}. '{out}' 를 닫고 다시 실행하세요.")
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    doc.close()

if __name__ == "__main__":
    main()
