import re


def _parse_selection(choice, max_n):
    choice = choice.strip().lower()
    if choice in ("all", "a"):
        return list(range(max_n))
    indices = []
    for part in re.split(r"[,\s]+", choice):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                indices.extend(range(int(a) - 1, int(b)))
            except ValueError:
                pass
        else:
            try:
                indices.append(int(part) - 1)
            except ValueError:
                pass
    return sorted(set(i for i in indices if 0 <= i < max_n))
