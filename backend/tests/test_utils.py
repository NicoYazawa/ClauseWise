"""Unit tests for the utils layer: clause splitting / encryption / diff / files / masking."""
from __future__ import annotations

import pytest

from app.core.exceptions import AppError
from app.utils import clause_split, crypto, diff, files, mask


# ===================== clause_split =====================
class TestClassifyClause:
    def test_title_hit_wins_over_body(self):
        # title match on "违约责任" wins; even when the body contains "交付", it still classifies as 违约责任
        assert clause_split.classify_clause("违约责任：交付时间与验收标准") == "违约责任"

    def test_body_fallback_first_120_chars(self):
        assert clause_split.classify_clause("双方约定保密信息范围") == "保密"

    def test_keyword_beyond_120_chars_ignored(self):
        text = "双方约定" + "x" * 200 + "仲裁"
        assert clause_split.classify_clause(text) == "其他约定"

    def test_no_keyword(self):
        assert clause_split.classify_clause("双方另行协商解决") == "其他约定"

    def test_rule_priority_order(self):
        # "争议" has the highest priority: when the title contains both 争议/违约, it classifies as 争议解决
        assert clause_split.classify_clause("争议与违约责任：仲裁") == "争议解决"


class TestExtractClauseNo:
    @pytest.mark.parametrize("text,expected", [
        ("第一条 标的", "第一条"),
        ("第十二条 价款", "第十二条"),
        ("第1条 价款", "第1条"),
        ("5.1.2 验收标准", "5.1.2"),
        ("无编号正文", "未编号"),
        ("  第三条  trim", "第三条"),
    ])
    def test_extract(self, text, expected):
        assert clause_split.extract_clause_no(text) == expected

    def test_truncate_to_32(self):
        long_no = "第" + "零" * 50 + "条"
        assert len(clause_split.extract_clause_no(long_no + " 正文")) <= 32


class TestSplitClauses:
    def test_basic_two_clauses(self):
        pages = ["第一条 付款方式\n甲方支付价款。\n第二条 交付\n乙方交付货物。"]
        out = clause_split.split_clauses(pages)
        assert [c["clause_no"] for c in out] == ["第一条", "第二条"]
        assert out[0]["clause_type"] == "付款"
        assert out[0]["page_no"] == 1
        assert out[0]["char_start"] == 0
        assert out[0]["char_end"] == out[1]["char_start"]  # cut at the start of the next clause number

    def test_preamble_merged_into_first_clause(self):
        pages = ["合同编号 HT-001\n第一条 标的\n采购设备。"]
        out = clause_split.split_clauses(pages)
        assert len(out) == 1
        assert "合同编号" in out[0]["content"]

    def test_empty_pages(self):
        assert clause_split.split_clauses(["", "  "]) == []

    def test_no_clause_number_single_block(self):
        pages = ["这是一段没有条款号的完整合同正文，超过八个字符。"]
        out = clause_split.split_clauses(pages)
        assert len(out) == 1
        assert out[0]["clause_no"] == "未编号"

    def test_noise_dropped_short(self):
        pages = ["第一条 甲\n第二条 乙"]
        out = clause_split.split_clauses(pages)
        assert out == []  # all below 8 chars

    def test_page_mapping_multi_page(self):
        pages = ["第一条 付款\n" + "a" * 30, "第二条 交付\n" + "b" * 30]
        out = clause_split.split_clauses(pages)
        assert [c["page_no"] for c in out] == [1, 2]

    def test_long_clause_split_by_sentence(self):
        long_text = "第一条 付款\n" + "。".join(f"第{i}段付款约定内容" for i in range(120))
        out = clause_split.split_clauses([long_text])
        assert len(out) > 1
        assert all(len(c["content"]) <= 1200 for c in out)

    def test_page_of_fallback(self):
        assert clause_split._page_of([(0, 5, 1), (6, 10, 2)], 100) == 2
        assert clause_split._page_of([], 3) == 1


# ===================== crypto =====================
class TestCrypto:
    def test_roundtrip(self):
        enc = crypto.encrypt_text("91110100MA00X0Y0Z0")
        assert enc.startswith("enc:")
        assert crypto.decrypt_text(enc) == "91110100MA00X0Y0Z0"

    def test_none_and_empty(self):
        assert crypto.encrypt_text(None) is None
        assert crypto.encrypt_text("") == ""
        assert crypto.decrypt_text(None) is None
        assert crypto.decrypt_text("") == ""

    def test_idempotent(self):
        once = crypto.encrypt_text("secret")
        assert crypto.encrypt_text(once) == once

    def test_legacy_plaintext_tolerated(self):
        assert crypto.decrypt_text("plain-not-encrypted") == "plain-not-encrypted"

    def test_ciphertext_differs_each_time(self):
        a, b = crypto.encrypt_text("same"), crypto.encrypt_text("same")
        assert a != b  # random nonce


# ===================== diff =====================
class TestDiff:
    def test_similarity(self):
        assert diff.text_similarity("abc", "abc") == 1.0
        assert diff.text_similarity("", "") == 1.0
        assert diff.text_similarity("abc", "") == 0.0
        assert diff.text_similarity("", "abc") == 0.0
        assert 0 < diff.text_similarity("abcdef", "abcxyz") < 1

    def test_summary_equal(self):
        assert diff.char_diff_summary("一样", "一样") == "两版本文本一致。"

    def test_summary_replace_delete_insert(self):
        s = diff.char_diff_summary("旧条款内容", "新条款内容")
        assert "改为" in s or "删除" in s or "新增" in s

    def test_summary_insert_only(self):
        s = diff.char_diff_summary("", "纯新增内容")
        assert s.startswith("新增「纯新增内容」")

    def test_summary_delete_only(self):
        s = diff.char_diff_summary("纯删除内容", "")
        assert s.startswith("删除「纯删除内容」")

    def test_summary_more_than_six_ops(self):
        old = "。".join(f"旧内容{i}" for i in range(10))
        new = "。".join(f"新内容{i}" for i in range(10))
        assert diff.char_diff_summary(old, new).endswith(" 等")


# ===================== files =====================
class TestFiles:
    @pytest.mark.parametrize("name,ext", [
        ("contract.PDF", ".pdf"), ("a.docx", ".docx"), ("scan.jpg", ".jpg"),
        ("scan.JPEG", ".jpeg"), ("shot.png", ".png"),
    ])
    def test_validate_upload_ok(self, name, ext):
        assert files.validate_upload(name, 1024) == ext

    def test_validate_upload_bad_ext(self):
        with pytest.raises(AppError) as ei:
            files.validate_upload("a.txt", 10)
        assert ei.value.status_code == 400
        assert ei.value.detail["code"] == "FILE_UNSUPPORTED_FORMAT"

    def test_validate_upload_too_large(self):
        with pytest.raises(AppError) as ei:
            files.validate_upload("a.pdf", files.MAX_FILE_SIZE + 1)
        assert ei.value.detail["code"] == "FILE_TOO_LARGE"

    def test_sha256(self):
        assert files.sha256_bytes(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

    @pytest.mark.parametrize("name,expected", [
        ("../../etc/passwd", "etc_passwd"),
        ('a\\b/c:d*e?f"g<h>i|j', "a_b_c_d_e_f_g_h_i_j"),
        ("  ..  ", "unnamed"),
        ("x" * 200 + ".pdf", "x" * 120),
    ])
    def test_sanitize_filename(self, name, expected):
        assert files.sanitize_filename(name) == expected

    def test_contract_dir_and_save_origin(self, storage_root):
        d = files.contract_dir(7)
        assert d.exists()
        rel, sha = files.save_origin_file(7, 2, "../evil name.pdf", b"data")
        assert rel == "contracts/7/origin/v2_evil name.pdf"
        assert sha == files.sha256_bytes(b"data")
        assert (storage_root / rel).exists()

    def test_resolve_storage_path_ok(self, storage_root):
        (storage_root / "contracts").mkdir(parents=True, exist_ok=True)
        (storage_root / "contracts" / "a.pdf").write_bytes(b"x")
        p = files.resolve_storage_path("contracts/a.pdf")
        assert p.exists()

    def test_resolve_storage_path_traversal(self):
        with pytest.raises(AppError) as ei:
            files.resolve_storage_path("../../secret.txt")
        assert ei.value.detail["code"] == "FILE_PATH_TRAVERSAL"


# ===================== mask =====================
class TestMask:
    @pytest.mark.parametrize("phone,expected", [
        ("13812345678", "138****5678"),
        ("138", "138"), (None, ""), ("", ""),
    ])
    def test_mask_phone(self, phone, expected):
        assert mask.mask_phone(phone) == expected

    @pytest.mark.parametrize("id_no,expected", [
        ("91110100MA00X0Y0Z0", "911" + "*" * 13 + "Z0"),
        ("short", "short"), (None, ""), ("", ""),
    ])
    def test_mask_id_no(self, id_no, expected):
        assert mask.mask_id_no(id_no) == expected
