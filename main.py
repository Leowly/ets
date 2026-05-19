import argparse
import os
import shutil
import sys

from reader.rish import PersistentRish, RishFileReader
from reader.local import LocalFileReader
from parser.discover import discover_exams, build_section_map, exam_summary
from parser.extractor import extract_exam
from utils.selector import _parse_selection

DEFAULT_RISH_DIR = "/storage/emulated/0/Android/data/com.ets100.secondary/files/Download/ETS_secondary/resource"
DEFAULT_LOCAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resource")

IS_ANDROID = hasattr(sys, "getandroidapilevel")


def main():
    # ── 平台检测 & 回退 ──────────────────────────────────────────
    if IS_ANDROID:
        if shutil.which("rish"):
            use_rish = True
        elif os.path.isdir(DEFAULT_LOCAL_DIR):
            print("[提示] 未检测到 rish，回退到本地 resource/ 目录")
            use_rish = False
        else:
            print("\n[错误] 未检测到 rish，且项目目录下未找到 resource/ 文件夹。")
            print("请选择以下方式之一提供数据：")
            print(f"  1. 配置 Shizuku + rish，使 rish 位于 PATH 中")
            print(f"     下载 Shizuku: https://shizuku.rikka.app/download/")
            print(f"  2. 将 ETS 的 resource 文件夹复制到本脚本同目录下：")
            print(f"     {DEFAULT_LOCAL_DIR}")
            return
    else:
        if os.path.isdir(DEFAULT_LOCAL_DIR):
            use_rish = False
        else:
            print("\n[错误] 项目目录下未找到 resource/ 文件夹。")
            print("请选择以下方式之一提供数据：")
            print(f"  1. 修改 main.py 中的 DEFAULT_LOCAL_DIR，指向你的 resource 目录")
            print(f"     当前值: {DEFAULT_LOCAL_DIR}")
            print(f"  2. 将 resource 文件夹复制到脚本同目录下")
            return

    # ── CLI ────────────────────────────────────────────────────────
    if use_rish:
        default_dir = DEFAULT_RISH_DIR
        description = "通过 Shizuku rish 从 ETS Android 数据目录提取试卷"
    else:
        default_dir = DEFAULT_LOCAL_DIR
        description = "从 ETS 数据目录提取试卷"

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--dir", default=default_dir, help=f"数据源目录 (默认: {default_dir})")
    parser.add_argument("--output", default="./result", help="输出目录 (默认: ./result)")
    parser.add_argument("--exam", type=str, default=None, help="提取指定试卷编号（逗号分隔、范围、all）")
    parser.add_argument("--list", action="store_true", help="仅列出可提取的试卷")
    parser.add_argument("--all", action="store_true", help="提取全部试卷")

    args = parser.parse_args()

    # ── 创建 reader ─────────────────────────────────────────────────
    if use_rish:
        shell = PersistentRish()
        reader = RishFileReader(shell, base_path=args.dir)
    else:
        reader = LocalFileReader(base_path=args.dir)
        shell = None

    try:
        if not reader.exists(""):
            if use_rish:
                print(f"\n[错误] rish 无法访问该目录: {args.dir}")
                print("请检查包名是否正确，或者是否已授予 Shizuku 权限。")
            else:
                print(f"\n[错误] 无法访问该目录: {args.dir}")
                print("请检查路径是否正确，或使用 --dir 参数指定正确的目录。")
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
        if shell:
            shell.close()


if __name__ == "__main__":
    main()
