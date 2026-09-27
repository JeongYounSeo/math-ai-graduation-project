"""문제 이미지 위에 problem_regions 절취선을 그려 저장한다.

사용법:
    python draw_region_overlay.py <problem_id> [db_path]

- problem_id: 대상 문제 id
- db_path: 선택. 기본 ./math_problem_engine.db
출력: ./region_overlay_<problem_id>.png

region_type 별 색:
    QUESTION_TEXT=초록, STATEMENT_BOX=파랑, CHOICE_BOX=주황,
    DIAGRAM=빨강, TABLE=보라, CHOICE_OPTION=청록, 기타=회색
"""
import sys, os, json, sqlite3
from PIL import Image, ImageDraw

TYPE_COLORS = {
    "QUESTION_TEXT": "#3cb44b", "STATEMENT_BOX": "#4363d8",
    "CHOICE_BOX": "#f58231", "DIAGRAM": "#e6194B", "TABLE": "#911eb4",
    "choice_option": "#42d4f4", "choice_group": "#f032e6",
    "figure": "#e6194B", "graph": "#e6194B", "table": "#911eb4",
}

def main():
    if len(sys.argv) < 2:
        print("usage: python draw_region_overlay.py <problem_id> [db_path]")
        sys.exit(1)
    pid = int(sys.argv[1])
    db = sys.argv[2] if len(sys.argv) > 2 else "math_problem_engine.db"

    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute("SELECT problem_image_path FROM problems WHERE id=?", (pid,))
    row = cur.fetchone()
    if not row or not row[0]:
        print(f"problem {pid}: image_path 없음")
        sys.exit(1)
    img_path = row[0]
    if not os.path.exists(img_path):
        print(f"이미지 파일 없음: {img_path}")
        sys.exit(1)

    img = Image.open(img_path).convert("RGB")
    W, H = img.size
    draw = ImageDraw.Draw(img)

    cur.execute(
        "SELECT region_type, bounding_box, image_path FROM problem_regions "
        "WHERE problem_id=? ORDER BY order_index", (pid,)
    )
    regs = cur.fetchall()
    con.close()

    if not regs:
        print(f"problem {pid}: region 0개 (재추출 필요? Vision 키 확인)")

    print(f"problem {pid}: 이미지 {W}x{H}, region {len(regs)}개")
    for rt, bb, ip in regs:
        d = json.loads(bb) if isinstance(bb, str) else bb
        l, t, r, b = d["left"], d["top"], d["right"], d["bottom"]
        color = TYPE_COLORS.get(rt, "#808080")
        for off in range(3):
            draw.rectangle([l+off, t+off, r-off, b-off], outline=color)
        draw.rectangle([l, t, l+len(rt)*8+6, t+18], fill=color)
        draw.text((l+3, t+3), rt, fill="white")
        flag = " [img]" if ip else ""
        print(f"  {rt}: ({l:.0f},{t:.0f},{r:.0f},{b:.0f}){flag}")

    outp = f"region_overlay_{pid}.png"
    img.save(outp)
    print(f"저장: {outp}")

if __name__ == "__main__":
    main()
