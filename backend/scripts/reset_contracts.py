"""Clear contract-domain data (destructive; must be run explicitly):

- MySQL: contract / contract_version / contract_clause / review_task / risk_finding /
  review_report / workflow_instance / approval_record / notification / audit_log (historical audit)
- ES: delete and rebuild contract_index / report_index (legal_knowledge / template_clause knowledge bases are kept)
- Local files: clear all originals under STORAGE_ROOT/contracts and historical logs under data/logs

Usage (from the backend directory):
    python scripts/reset_contracts.py
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

# Deletion order: children before parents (foreign-key dependency)
TABLES = [
    "approval_record",
    "workflow_instance",
    "review_report",
    "risk_finding",
    "review_task",
    "contract_clause",
    "contract_version",
    "contract",
    "notification",
    "audit_log",
]


def reset_mysql() -> None:
    with engine.begin() as conn:
        total = 0
        for t in TABLES:
            n = conn.execute(text(f"DELETE FROM `{t}`")).rowcount
            total += n
            print(f"  {t:<20} 清除 {n} 行")
        for t in ("contract", "contract_version", "contract_clause", "review_task",
                  "risk_finding", "review_report", "workflow_instance", "approval_record",
                  "notification", "audit_log"):
            conn.execute(text(f"ALTER TABLE `{t}` AUTO_INCREMENT = 1"))
        print(f"MySQL 合同域数据已清空（共 {total} 行，自增 ID 已重置）")


def reset_es() -> None:
    try:
        from app.es.client import get_es_client
        from app.es.indices import INDEX_CONTRACT, INDEX_REPORT, _analyzer_settings, _contract_mapping, _vector_mapping

        es = get_es_client()
        if es is None:
            print("ES 不可用，跳过索引重置（检索功能将返回空结果）")
            return
        for name in (INDEX_CONTRACT, INDEX_REPORT):
            if es.indices.exists(index=name):
                es.indices.delete(index=name)
        base_settings = {"number_of_shards": 1, "number_of_replicas": 0}
        ik = _analyzer_settings()
        if ik:
            base_settings.update(ik)
        es.indices.create(index=INDEX_CONTRACT, mappings=_contract_mapping(), settings=base_settings)
        es.indices.create(index=INDEX_REPORT, mappings=_vector_mapping(), settings=base_settings)
        print("ES contract_index / report_index 已删除并重建（知识库索引保留）")
    except Exception as e:  # noqa: BLE001
        print(f"ES 重置失败：{e}（不阻塞，可稍后重跑）")


def reset_files() -> None:
    d = settings.storage_path / "contracts"
    if d.exists():
        shutil.rmtree(d)
        print(f"本地合同文件已清空：{d}")
    else:
        print("本地无合同文件目录，跳过")
    # Historical logs (app / audit): only delete files, keep directories; skip if in use
    logs = Path(__file__).resolve().parent.parent / "data" / "logs"
    n_log = 0
    if logs.exists():
        for f in logs.rglob("*"):
            if f.is_file():
                try:
                    f.unlink()
                    n_log += 1
                except OSError:
                    print(f"  日志被占用跳过：{f.name}")
    print(f"历史日志文件已清除 {n_log} 个（目录保留）")


if __name__ == "__main__":
    print("=" * 56)
    print("AI智能合同合规审查平台 · 合同域数据清空")
    print("=" * 56)
    reset_mysql()
    reset_es()
    reset_files()
    print("完成。合同列表已置空，可上传新的合同文件。")
