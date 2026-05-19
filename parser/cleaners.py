import re


def strip_html(text):
    text = re.sub(r"</p>\s*<p>", " ", str(text))
    text = re.sub(r"<[^>]+>", "", text)
    return text


def clean(text):
    return re.sub(r"^ets_th\d+\s*", "", strip_html(text)).strip()


def qnum(nr):
    return nr.strip().rstrip(".")
