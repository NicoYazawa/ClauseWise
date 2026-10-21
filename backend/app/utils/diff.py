"""Version diff utilities (design doc 3.1.4): character-level difflib + clause-level semantic comparison helpers."""
import difflib


def text_similarity(a: str, b: str) -> float:
    """Character-level similarity (SequenceMatcher.ratio)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def char_diff_summary(old: str, new: str) -> str:
    """Line-level add/remove description (fallback copy for the frontend two-pane view)."""
    sm = difflib.SequenceMatcher(None, old, new)
    ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
    if not ops:
        return "两版本文本一致。"
    parts = []
    for tag, i1, i2, j1, j2 in ops[:6]:
        if tag == "replace":
            parts.append(f"「{old[i1:i2][:24]}」改为「{new[j1:j2][:24]}」")
        elif tag == "delete":
            parts.append(f"删除「{old[i1:i2][:24]}」")
        elif tag == "insert":
            parts.append(f"新增「{new[j1:j2][:24]}」")
    suffix = " 等" if len(ops) > 6 else ""
    return "；".join(parts) + suffix
