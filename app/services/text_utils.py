from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


def clean_header(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_text(value: object) -> str:
    text = str(value or "").strip().upper()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_supplier(value: object) -> str:
    text = normalize_text(value)
    noise = {
        "LTDA", "S A", "SA", "ME", "EPP", "EIRELI", "DO", "DA", "DE", "DOS", "DAS",
        "BRASIL", "BRASILEIRA", "BRASILEIRO", "COMERCIO", "INDUSTRIA", "SERVICOS", "SERVICO",
    }
    tokens = [token for token in text.split() if token not in noise]
    return " ".join(tokens)


def supplier_similarity(a: object, b: object) -> float:
    na = normalize_supplier(a)
    nb = normalize_supplier(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    sa, sb = set(na.split()), set(nb.split())
    token_score = len(sa & sb) / max(1, len(sa | sb))
    seq_score = SequenceMatcher(None, na, nb).ratio()
    return max(seq_score, 0.65 * token_score + 0.35 * seq_score)
