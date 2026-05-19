import argparse
import os

from reader.rish import PersistentRish, RishFileReader
from parser.discover import discover_exams, build_section_map, exam_summary
from parser.extractor import extract_exam
from utils.selector import _parse_selection

DEFAULT_RISH_DIR = "/storage/emulated/0/Android/data/com.ets100.secondary/files/Download/ETS_secondary/resource"


def main():
    parser = argparse.ArgumentParser(description="通过 Shizuku rish 从 ETS Android 数据目录提取试卷")
    parser.add_argument("--dir", default=DEFAULT_RISH_DIR, help=f"Android源目录 (默认: {DEFAULT_RISH_DIR})")
    parser.add_argument("--output", default="./result", help="输出到本地的目录 (默认: 当前目录下的 ./result)")
    parser.add_argument("--exam", type=str, default=None, help="提取指定试卷编号（支持逗号分隔、范围、all）")
    parser.add_argument("--list", action="store_true", help="仅列出可提取的试卷")
    parser.add_argument("--all", action="store_true", help="提取全部试卷")

    args = parser.parse_args()

    shell = PersistentRish()
    try:
        reader = RishFileReader(shell, base_path=args.dir)

        if not reader.exists(""):
            print(f"\n[错误] rish 无法访问该目录: {args.dir}")
            print("请检查包名是否正确，或者是否已授予 Shizuku 权限。")
            return

        exams = discover_exams(reader)
        if not exams:
            print(f"\n在 {args.dir} 中未发现试卷数据。")
            return

        if args.list:
            print(f"\n发现 {len(exams)} 套试卷：")
            for i, items in enumerate(exams, 1):
                print(f"  {i:>2}. {exam_summary(items)}")
            return

        out_dir = os.path.abspath(args.output)

        if args.all:
            selected = list(range(len(exams)))
        elif args.exam:
            selected = _parse_selection(args.exam, len(exams))
        elif len(exams) == 1:
            selected = [0]
        else:
            print(f"\n发现 {len(exams)} 套试卷：")
            for i, items in enumerate(exams, 1):
                print(f"  {i:>2}. {exam_summary(items)}")
            print()
            choice = input("请选择要提取的试卷编号（支持多选，如 1,3,5 或 all）：").strip()
            selected = _parse_selection(choice, len(exams))
            if not selected:
                print("未选中任何试卷，退出。")
                return

        multi = len(selected) > 1 or (len(exams) > 1 and len(selected) == 1)
        total = 0

        print(f"\n开始提取，结果将保存至本地: {out_dir}\n")

        for idx in selected:
            items = exams[idx]
            section_map = build_section_map(items)

            if multi:
                q_path = os.path.join(out_dir, f"试卷{idx + 1}.txt")
                a_path = os.path.join(out_dir, f"答案{idx + 1}.txt")
            else:
                q_path = os.path.join(out_dir, "试题.txt")
                a_path = os.path.join(out_dir, "答案.txt")

            n = extract_exam(items, section_map, q_path, a_path)
            total += n
            print(f"  [{idx + 1}] {exam_summary(items)}")
            print(f"       试题 → {q_path}")
            print(f"       答案 → {a_path}")

        print(f"\n完成！共提取 {total} 题（{len(selected)} 套试卷）")

    finally:
        shell.close()


if __name__ == "__main__":
    main()
