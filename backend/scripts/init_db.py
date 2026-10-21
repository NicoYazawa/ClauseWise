"""One-shot initialization: create DB (utf8mb4) -> create tables -> seed data (full migration of the former frontend mock) -> ES indices + knowledge vectorization.

Usage (from the backend directory):
    python scripts/init_db.py            # idempotent: existing data is skipped
    python scripts/init_db.py --reset    # destructive: drops and rebuilds all tables and ES indices
"""
import sys
import secrets
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password, validate_password
from app.core.permissions import PERMISSIONS, UPGRADE_GRANTS
from app.core.preset_accounts import PRESET_ACCOUNTS, effective_password  # noqa: E402
from app.db.security_upgrade import (  # noqa: E402
    harden_legacy_accounts,
    migrate_legacy_reports,
    seed_preset_accounts,
    sync_permissions,
    upgrade_schema,
)
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    ApprovalRecord,
    AuditLog,
    Contract,
    ContractClause,
    ContractTemplate,
    ContractVersion,
    LawRegulation,
    ModelVersion,
    Notification,
    Permission,
    PromptTemplate,
    ReviewReport,
    ReviewTask,
    RiskFinding,
    Role,
    User,
    WorkflowDefinition,
    WorkflowInstance,
)
from app.utils.crypto import encrypt_text  # noqa: E402

RESET = "--reset" in sys.argv


def dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")


def d(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


def create_database():
    """Create the database: utf8mb4 / utf8mb4_unicode_ci (design doc 3.1.5).

    In container deployments the database is pre-created by the MySQL image, and the app account may lack
    CREATE DATABASE permission; in that case we only log a hint and continue (table structure is still
    handled by create_tables).
    """
    url = (
        f"mysql+pymysql://{settings.mysql_user}:{settings.mysql_password}"
        f"@{settings.mysql_host}:{settings.mysql_port}?charset=utf8mb4"
    )
    e = create_engine(url)
    try:
        with e.connect() as conn:
            conn.execute(
                text(
                    "CREATE DATABASE IF NOT EXISTS `contract_compliance` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
            conn.commit()
        print("[1/7] 数据库 contract_compliance 已就绪（utf8mb4）")
    except Exception as exc:  # noqa: BLE001 权限不足时假设数据库已存在
        print(f"[1/7] 跳过建库（{exc}），假设数据库已存在")
    finally:
        e.dispose()


def create_tables():
    if RESET:
        Base.metadata.drop_all(engine)
        print("  -- 已清空全部数据表（--reset）")
    upgrade_schema(engine)
    print("[2/7] 数据表已创建（21 张）")


# ===================== Seed data =====================


ROLES = [
    ("admin", "系统管理员", "维护知识库、模板、账号与权限，全模块管理", "all",
     ["contract:upload", "contract:download", "contract:delete", "review:rerun", "review:export",
      "workflow:define", "workflow:approve", "knowledge:manage", "system:user", "system:role", "system:audit"]),
    ("legal_manager", "法务主管", "复核高风险合同，参与法务加签审批", "all",
     ["contract:download", "review:rerun", "review:export", "workflow:approve", "knowledge:manage"]),
    ("legal_reviewer", "法务审查员", "出具审查意见，处置风险发现", "all",
     ["contract:download", "review:rerun", "review:export", "knowledge:manage"]),
    ("business_owner", "业务经办人", "上传合同、发起审查与审批、跟踪进度", "dept",
     ["contract:upload", "contract:download", "review:export"]),
    ("auditor", "审计员", "只读审计，查看全链路操作日志", "all", ["system:audit"]),
    ("dept_manager", "部门经理", "审批节点角色，负责本部门合同初审", "dept",
     ["contract:download", "workflow:approve"]),
]

USERS = PRESET_ACCOUNTS

LAWS = [
    # (doc_type, title, content, source_ref, effective, expiry, status, vectorized, hit)
    ("law", "《民法典》第四百六十九条", "当事人订立合同，可以采用书面形式、口头形式或者其他形式。", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 12),
    ("law", "《民法典》第四百七十条", "合同的内容由当事人约定，一般包括下列条款：（一）当事人的姓名或者名称和住所；（二）标的；（三）数量；（四）质量；（五）价款或者报酬；（六）履行期限、地点和方式；（七）违约责任；（八）解决争议的方法。", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 21),
    ("law", "《民法典》第四百九十六条", "格式条款是当事人为了重复使用而预先拟定，并在订立合同时未与对方协商的条款。采用格式条款订立合同的，提供格式条款的一方应当遵循公平原则确定当事人之间的权利和义务，并采取合理的方式提示对方注意免除或者减轻其责任等与对方有重大利害关系的条款……", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 35),
    ("law", "《民法典》第四百九十七条", "有下列情形之一的，该格式条款无效：（一）具有本法第一编第六章第三节和本法第五百零六条规定的无效情形；（二）提供格式条款一方不合理地免除或者减轻其责任、加重对方责任、限制对方主要权利；（三）提供格式条款一方排除对方主要权利。", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 18),
    ("law", "《民法典》第五百零二条", "依法成立的合同，自成立时生效，但是法律另有规定或者当事人另有约定的除外。", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 8),
    ("law", "《民法典》第五百零六条", "合同中的下列免责条款无效：（一）造成对方人身损害的；（二）因故意或者重大过失造成对方财产损失的。", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 42),
    ("law", "《民法典》第五百一十条", "合同生效后，当事人就质量、价款或者报酬、履行地点等内容没有约定或者约定不明确的，可以协议补充；不能达成补充协议的，按照合同相关条款或者交易习惯确定。", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 16),
    ("law", "《民法典》第五百六十三条", "有下列情形之一的，当事人可以解除合同：（一）因不可抗力致使不能实现合同目的；（二）在履行期限届满前，当事人一方明确表示或者以自己的行为表明不履行主要债务……", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 9),
    ("law", "《民法典》第五百七十七条", "当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 27),
    ("law", "《民法典》第五百八十四条", "当事人一方不履行合同义务或者履行合同义务不符合约定，造成对方损失的，损失赔偿额应当相当于因违约所造成的损失，包括合同履行后可以获得的利益；但是，不得超过违约一方订立合同时预见到或者应当预见到的因违约可能造成的损失。", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 14),
    ("law", "《民法典》第五百八十五条", "当事人可以约定一方违约时应当根据违约情况向对方支付一定数额的违约金，也可以约定因违约产生的损失赔偿额的计算方法。约定的违约金低于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以增加；约定的违约金过分高于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以适当减少。", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 58),
    ("law", "《民法典》第五百九十条", "当事人一方因不可抗力不能履行合同的，根据不可抗力的影响，部分或者全部免除责任，但是法律另有规定的除外。", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 6),
    ("law", "《民法典》第七百零五条", "租赁期限不得超过二十年。超过二十年的，超过部分无效。", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 11),
    ("law", "《民法典》第七百零七条", "租赁期限六个月以上的，应当采用书面形式。当事人未采用书面形式，无法确定租赁期限的，视为不定期租赁。", "全国人民代表大会 2020 年颁布", "2021-01-01", None, "active", True, 5),
    ("law", "《劳动合同法》第五十八条", "劳务派遣单位是本法所称用人单位，应当履行用人单位对劳动者的义务。劳务派遣单位与被派遣劳动者订立的劳动合同，除应当载明本法第十七条规定的事项外，还应当载明被派遣劳动者的用工单位以及派遣期限、工作岗位等情况。", "全国人民代表大会常务委员会 2012 年修正", "2013-07-01", None, "active", True, 19),
    ("case", "指导案例 64 号：违约金调整纠纷案", "当事人约定的违约金超过造成损失的百分之三十的，一般可以认定为「过分高于造成的损失」，可依当事人请求予以适当减少。", "最高人民法院审判委员会 发布", "2016-09-19", None, "active", True, 23),
    ("law", "《合同法》（已失效）第一百一十四条", "（该法已于 2021-01-01 废止，由《民法典》承继）当事人可以约定一方违约时应当根据违约情况向对方支付一定数额的违约金……", "全国人民代表大会 1999 年颁布", "1999-10-01", "2020-12-31", "expired", True, 0),
]

TEMPLATES = [
    (1, "标的与质量条款", "purchase", "required", "乙方供应的货物应为原厂全新正品，符合国家标准、行业标准及双方确认的技术协议；整机质保期不低于三年。", 4),
    (2, "付款条款", "purchase", "required", "预付款不超过合同总价的 30%；到货验收合格后支付至 95%；余款 5% 作为质保金，质保期满后 15 日内付清。付款前乙方应开具等额增值税专用发票。", 4),
    (3, "违约责任条款", "purchase", "required", "任一方逾期履行的，每逾期一日按合同总价的 0.05% 支付违约金，累计不超过合同总价的 10%；造成损失的按实际损失赔偿。", 4),
    (4, "交付与验收条款", "purchase", "recommended", "乙方应在收到预付款后 30 日内交货；甲方应在到货后 10 日内按技术协议组织验收，验收不合格的，乙方应在 15 日内更换或修复。", 4),
    (5, "保密条款", "purchase", "optional", "双方对履约过程中知悉的商业秘密保密，保密期限至合同终止后三年。", 4),
    (6, "价款与结算条款", "sales", "required", "合同总价包含全部费用；分三期支付（生效 40%、验收 40%、试运行 20%）；发票类型与开具时间明确约定。", 3),
    (7, "交付与风险转移条款", "sales", "required", "标的物毁损、灭失的风险，交付前由乙方承担，交付后由甲方承担。", 3),
    (8, "所有权保留条款", "sales", "recommended", "甲方未付清全部价款前，标的物所有权归乙方所有；甲方付清全部价款后所有权自动转移。", 3),
    (9, "售后服务条款", "sales", "optional", "乙方提供不少于一年的免费维护期，响应时限 4 小时，重大故障 24 小时内到场。", 3),
    (10, "派遣岗位与期限条款", "labor", "required", "派遣岗位、人数、派遣期限应明确约定；派遣期限应符合《劳动合同法》规定，一般不低于两年。", 2),
    (11, "费用与工资条款", "labor", "required", "派遣费用按月结算；乙方应按时足额发放工资并缴纳社会保险，不得拖欠、克扣。", 2),
    (12, "保密与竞业限制条款", "labor", "recommended", "保密期限为合同终止后五年；竞业限制应约定经济补偿，期限不超过两年。", 2),
    (13, "培训服务期条款", "labor", "optional", "乙方为人员提供专项培训的，可约定服务期与违约金，违约金不超过培训费用。", 2),
    (14, "租赁物与租金条款", "lease", "required", "租赁物明细、租金标准、支付周期与递增机制应明确约定；租期超过二十年的部分无效。", 2),
    (15, "维修责任条款", "lease", "required", "出租人应保持租赁物符合约定用途；自然损耗的维修由出租人承担，使用不当造成的损坏由承租人承担。", 2),
    (16, "优先承租权条款", "lease", "recommended", "租赁期满承租人继续使用的，同等条件下享有优先承租权。", 2),
    (17, "装修与复原条款", "lease", "optional", "承租人对租赁物装修应经出租人书面同意，退租时按约定复原或折价补偿。", 2),
    (18, "保密信息范围条款", "nda", "required", "保密信息包括技术信息、经营信息、双方履约过程中知悉的其他未公开信息；范围应采用列举加概括方式界定。", 3),
    (19, "保密期限条款", "nda", "required", "保密期限自合同签署之日起至合同终止后五年；技术核心秘密可约定至公开为止。", 3),
    (20, "违约责任条款", "nda", "required", "违反保密义务的，按实际损失赔偿；损失难以计算的，按约定违约金（不低于 10 万元）支付。", 3),
    (21, "例外情形条款", "nda", "recommended", "已经公开的信息、独立开发获得的信息、依法披露的信息不属于保密信息。", 3),
    (22, "信息回流条款", "nda", "optional", "合同终止后，任一方可要求对方返还或销毁载有保密信息的资料，并书面确认。", 3),
    (23, "争议解决条款", "other", "required", "因合同发生的争议，双方应友好协商；协商不成的，提交合同签订地有管辖权的人民法院诉讼解决（或提交 XX 仲裁委员会仲裁，二选一）。", 1),
    (24, "通知与送达条款", "other", "recommended", "双方应书面约定联系人、地址与电子邮箱；通知自送达或视为送达时生效。", 1),
]

CONTRACTS = [
    # (id, no, title, type, owner_id, owner_name, status, ver, cp_name, cp_idno, cp_phone, amount, created, updated)
    (1, "HT-2026-0001", "服务器设备采购合同（二期扩容）", "purchase", 4, "parsing→审批", "in_approval", 2, "北京华创信息科技有限公司", "91110108MA01X2Y3Z4", "139****5678", 860000, "2026-08-18T10:12:00", "2026-08-26T15:40:00"),
    (2, "HT-2026-0002", "MES 制造执行系统销售合同", "sales", 4, "", "review_passed", 1, "苏州精工智能制造有限公司", "91320594MA12X3Y4Z5", "138****5432", 1280000, "2026-08-20T09:05:00", "2026-08-27T11:20:00"),
    (3, "HT-2026-0003", "劳务派遣服务合同", "labor", 7, "", "review_blocked", 1, "上海众合人力资源服务有限公司", "91310115MA23X4Y5Z6", "137****6666", 360000, "2026-08-21T14:30:00", "2026-08-27T16:05:00"),
    (4, "HT-2026-0004", "办公楼三层场地租赁合同", "lease", 7, "", "in_approval", 1, "深圳市远置业发展有限公司", "91440300MA34X5Y6Z7", "136****5555", 540000, "2026-08-22T09:40:00", "2026-08-26T10:15:00"),
    (5, "HT-2026-0005", "核心算法技术保密协议", "nda", 3, "", "under_review", 1, "杭州数联科技有限公司", "91330106MA45X6Y7Z8", "135****4444", 0, "2026-08-25T16:20:00", "2026-08-28T09:10:00"),
    (6, "HT-2026-0006", "云计算资源框架采购合同", "purchase", 4, "", "parsing", 1, "中国云网技术服务有限公司", "91110108MA56X7Y8Z9", "134****3333", 720000, "2026-08-28T08:30:00", "2026-08-28T08:31:00"),
    (7, "HT-2026-0007", "钢材原材料采购合同（三季度）", "purchase", 7, "", "parse_failed", 1, "鞍山恒达钢铁贸易有限公司", "91210300MA67X8Y9Z0", "133****2222", 2150000, "2026-08-23T11:00:00", "2026-08-23T11:06:00"),
    (8, "HT-2026-0008", "品牌推广营销服务合同", "other", 4, "", "draft", 1, "广州创意无限广告有限公司", "91440101MA78X9Y0Z1", "132****0000", 98000, "2026-08-27T17:25:00", "2026-08-27T17:25:00"),
    (9, "HT-2026-0009", "生产设备年度维护服务合同", "other", 4, "", "approved", 1, "沈阳重工机械服务股份有限公司", "91210100MA89X0Y1Z2", "131****9999", 265000, "2026-08-12T10:00:00", "2026-08-25T14:00:00"),
    (10, "HT-2026-0010", "冷链物流运输服务合同", "other", 7, "", "rejected", 1, "武汉鲜达物流有限公司", "91420100MA90X1Y2Z3", "130****8888", 188000, "2026-08-14T13:30:00", "2026-08-24T09:50:00"),
    (11, "HT-2026-0011", "管理咨询服务合同", "other", 4, "", "archived", 1, "北京博思远略咨询有限公司", "91110108MA01A2B3C4", "139****7777", 150000, "2026-07-02T09:00:00", "2026-08-10T16:30:00"),
    (12, "HT-2026-0012", "办公用品季度采购合同", "purchase", 7, "", "parsed", 1, "得力集团华东销售有限公司", "91330200MA02B3C4D5", "138****1234", 46000, "2026-08-27T10:30:00", "2026-08-27T10:33:00"),
]

VERSIONS = [
    # (id, contract_id, ver, parent, file_name, size_kb, parse_status, channel, created)
    (101, 1, 1, None, "v1_服务器设备采购合同.pdf", 2480, "parsed", "text", "2026-08-18T10:12:00"),
    (102, 1, 2, 101, "v2_服务器设备采购合同_修订.pdf", 2560, "parsed", "mixed", "2026-08-26T15:38:00"),
    (103, 2, 1, None, "v1_MES销售合同.docx", 860, "parsed", "text", "2026-08-20T09:05:00"),
    (104, 3, 1, None, "v1_劳务派遣服务合同.pdf", 1320, "parsed", "vision", "2026-08-21T14:30:00"),
    (105, 4, 1, None, "v1_场地租赁合同.pdf", 1580, "parsed", "text", "2026-08-22T09:40:00"),
    (106, 5, 1, None, "v1_技术保密协议.docx", 320, "parsed", "text", "2026-08-25T16:20:00"),
    (107, 6, 1, None, "v1_云资源框架采购.pdf", 3120, "parsing", None, "2026-08-28T08:30:00"),
    (108, 7, 1, None, "v1_钢材采购合同扫描件.pdf", 5240, "failed", "vision", "2026-08-23T11:00:00"),
    (109, 12, 1, None, "v1_办公用品采购.pdf", 640, "parsed", "text", "2026-08-27T10:30:00"),
    (110, 9, 1, None, "v1_生产设备年度维护服务合同.pdf", 1840, "parsed", "text", "2026-08-12T10:00:00"),
    (111, 10, 1, None, "v1_冷链物流运输合同扫描件.pdf", 4360, "parsed", "vision", "2026-08-14T13:30:00"),
    (112, 11, 1, None, "v1_管理咨询服务合同.docx", 520, "parsed", "text", "2026-07-02T09:00:00"),
]

CLAUSES = [
    # (id, version_id, contract_id, no, type, content, page)
    (11, 101, 1, "第一条", "主体资格", "甲方（采购方）：华辰智造股份有限公司；乙方（供应方）：北京华创信息科技有限公司。双方经友好协商，就服务器设备采购事宜达成如下协议。", 1),
    (12, 101, 1, "第二条", "标的与质量", "乙方向甲方供应机架式服务器 120 台（型号 HC-R6300），整机质保三年，主要部件（CPU/内存/硬盘）原厂全新，符合国家相关质量标准。", 1),
    (13, 101, 1, "第三条", "价款", "合同总价为人民币 920,000 元（大写：玖拾贰万元整），包含设备价款、包装费及运输保险费。", 2),
    (14, 101, 1, "第四条", "付款", "合同签订后 10 个工作日内，甲方向乙方支付预付款 30%；设备到货验收合格后支付 60%；余款 10% 作为质保金，质保期满无质量问题后 15 日内付清。", 2),
    (15, 101, 1, "第五条", "交付与验收", "乙方应于收到预付款后 30 日内交货至甲方指定地点。甲方应在到货后 7 日内组织验收，验收标准按第二条执行；逾期未验收视为验收合格。", 3),
    (16, 101, 1, "第六条", "违约责任", "乙方逾期交货的，每逾期一日按合同总价的 0.5% 向甲方支付违约金；甲方逾期付款的，每逾期一日按应付款项的 0.05% 向乙方支付违约金。", 3),
    (17, 101, 1, "第七条", "保密", "双方对在履约过程中知悉的对方商业秘密负有保密义务，保密期限为合同终止后两年。", 4),
    (18, 101, 1, "第八条", "争议解决", "因本合同引起的争议，双方应友好协商解决；协商不成的，提交甲方所在地有管辖权的人民法院诉讼解决。", 4),
    (21, 102, 1, "第一条", "主体资格", "甲方（采购方）：华辰智造股份有限公司；乙方（供应方）：北京华创信息科技有限公司。双方本着平等自愿原则，经友好协商，就服务器设备采购事宜达成如下协议。", 1),
    (22, 102, 1, "第二条", "标的与质量", "乙方向甲方供应机架式服务器 120 台（型号 HC-R6300），整机质保五年，主要部件（CPU/内存/硬盘/电源）原厂全新，符合 GB/T 9813 相关质量标准。", 1),
    (23, 102, 1, "第三条", "价款", "合同总价为人民币 860,000 元（大写：捌拾陆万元整），包含设备价款、包装费、运输保险费及三年上门服务费。", 2),
    (24, 102, 1, "第四条", "付款", "合同签订后 10 个工作日内，甲方向乙方支付预付款 30%；设备到货验收合格后支付 65%；余款 5% 作为质保金，质保期满无质量问题后 15 日内付清。", 2),
    (25, 102, 1, "第五条", "交付与验收", "乙方应于收到预付款后 25 日内交货至甲方指定地点。甲方应在到货后 10 日内组织验收，验收标准按第二条及双方书面确认的技术协议执行。", 3),
    (26, 102, 1, "第六条", "违约责任", "乙方逾期交货的，每逾期一日按合同总价的 0.3% 向甲方支付违约金，累计不超过合同总价的 10%；甲方逾期付款的，每逾期一日按应付款项的 0.05% 向乙方支付违约金，累计不超过应付款项的 5%。", 3),
    (27, 102, 1, "第八条", "争议解决", "因本合同引起的争议，双方应友好协商解决；协商不成的，任何一方可向合同签订地有管辖权的人民法院提起诉讼。", 4),
    (28, 102, 1, "第九条", "环境保护", "乙方承诺包装材料符合国家环保要求，设备能耗等级不低于一级能效标准。", 4),
    (31, 103, 2, "第一条", "主体资格", "甲方（买方）：苏州精工智能制造有限公司；乙方（卖方）：华辰智造软件事业部。就 MES 制造执行系统许可与实施服务事宜订立本合同。", 1),
    (32, 103, 2, "第二条", "许可范围", "乙方授予甲方非独占、不可转让的软件使用许可，许可范围限于甲方苏州厂区三个生产车间，用户数上限 200。", 1),
    (33, 103, 2, "第三条", "价款", "合同总价人民币 1,280,000 元，包含软件许可费、实施服务费及一年期维护费。", 2),
    (34, 103, 2, "第四条", "付款", "合同生效后 15 日内支付 40%，系统上线验收后支付 40%，试运行满三个月支付剩余 20%。", 2),
    (35, 103, 2, "第五条", "实施与验收", "实施周期 90 日，以双方签署的《上线验收报告》为验收合格依据。", 3),
    (36, 103, 2, "第六条", "违约责任", "任一方违约给对方造成损失的，应承担赔偿责任，违约金上限为合同总价的 15%。", 3),
    (37, 103, 2, "第七条", "知识产权", "软件著作权归乙方所有；基于实施过程形成的定制开发成果，著作权归甲方所有。", 4),
    (38, 103, 2, "第八条", "争议解决", "因本合同发生争议，协商不成的，提交苏州仲裁委员会仲裁。", 4),
    (41, 104, 3, "第一条", "主体资格", "甲方（用工单位）：华辰智造股份有限公司；乙方（派遣单位）：上海众合人力资源服务有限公司。", 1),
    (42, 104, 3, "第二条", "派遣岗位", "乙方向甲方派遣生产线操作工 60 名、质检员 10 名，派遣期限为两年。", 1),
    (43, 104, 3, "第三条", "费用", "甲方按每人每月 5,000 元向乙方支付派遣服务费用，含工资、社保及管理费。", 2),
    (44, 104, 3, "第四条", "付款", "甲方于每月 10 日前向乙方支付上月派遣费用，乙方收到费用后 3 个工作日内发放工资。", 2),
    (45, 104, 3, "第六条", "违约责任", "乙方派遣人员不符合岗位要求的，甲方有权随时退回且不承担任何责任；乙方违约的，按每人每月费用的三倍支付违约金；甲方违约的，赔偿乙方全部损失，违约金不超过当月费用的 5%。", 3),
    (46, 104, 3, "第八条", "免责条款", "乙方派遣人员在岗期间发生的一切人身损害及其他损失，均与甲方无关，甲方不承担任何责任。", 3),
    (47, 104, 3, "第十条", "付款解释", "派遣人员工作质量的验收标准由甲方单方解释并认定。", 4),
    (48, 104, 3, "第十二条", "保密", "双方对知悉的商业秘密保密，保密期直至公开为止。", 4),
    (51, 109, 12, "第一条", "主体资格", "甲方：华辰智造股份有限公司；乙方：得力集团华东销售有限公司。就办公用品季度采购事宜订立本合同。", 1),
    (52, 109, 12, "第二条", "标的", "甲方按季度向乙方采购办公用品，品类以甲方订单为准，具体单价见附件价格清单。", 1),
    (53, 109, 12, "第三条", "付款", "双方按季度对账，甲方收到发票后 30 日内支付上季度货款。", 2),
    (54, 109, 12, "第四条", "争议解决", "因本合同发生争议，协商不成的，提交甲方所在地人民法院诉讼解决。", 2),
    (55, 110, 9, "第一条", "主体资格", "甲方（委托方）：华辰智造股份有限公司；乙方（服务方）：沈阳重工机械服务股份有限公司。就生产设备年度维护服务事宜订立本合同。", 1),
    (56, 110, 9, "第二条", "服务范围", "乙方为甲方厂区内 32 台数控加工中心及配套设备提供年度巡检、保养与故障维修服务，每月巡检不少于 2 次。", 1),
    (57, 110, 9, "第三条", "价款", "年度服务费总计人民币 265,000 元，包含人工、常规耗材及往返交通费用；更换重大部件费用另行结算。", 2),
    (58, 110, 9, "第四条", "付款", "合同生效后 10 日内支付 50%；服务期满且年度考核合格后支付剩余 50%。", 2),
    (59, 110, 9, "第五条", "服务时效", "乙方接到故障通知后 4 小时内响应，24 小时内到场处理；重大故障 48 小时内恢复生产。", 3),
    (60, 110, 9, "第六条", "违约责任", "乙方逾期响应的，按每日 2,000 元支付违约金，累计不超过年度服务费的 10%；任何一方违约应赔偿对方直接损失。", 3),
    (61, 110, 9, "第七条", "争议解决", "因本合同引起的争议，双方协商解决；协商不成的，提交甲方所在地有管辖权的人民法院诉讼解决。", 4),
    (62, 111, 10, "第一条", "主体资格", "甲方（托运方）：华辰智造股份有限公司；乙方（承运方）：武汉鲜达物流有限公司。就冷链物流运输服务事宜订立本合同。", 1),
    (63, 111, 10, "第二条", "运输标的", "运输标的为冷藏食品原料及半成品，全程温度要求 0～4℃，乙方车辆须配备温控记录仪并实时上传数据。", 1),
    (64, 111, 10, "第三条", "价款", "运费按车次结算，年度预计总额人民币 188,000 元，含装卸费与货物运输保险费。", 2),
    (65, 111, 10, "第四条", "交付与验收", "乙方应在发运后 36 小时内送达甲方华东仓；收货时甲方抽检温度记录，超温批次有权拒收并要求 24 小时内补货。", 2),
    (66, 111, 10, "第五条", "违约责任", "因乙方温控不当造成货物变质损失的，乙方按货值全额赔偿，并按每车次 3,000 元支付违约金。", 3),
    (67, 112, 11, "第一条", "主体资格", "甲方（委托方）：华辰智造股份有限公司；乙方（受托方）：北京博思远略咨询有限公司。就管理咨询服务事宜订立本合同。", 1),
    (68, 112, 11, "第二条", "服务内容", "乙方为甲方提供精益生产体系咨询服务，含现场诊断、方案设计、落地辅导三个阶段，服务期 6 个月。", 1),
    (69, 112, 11, "第三条", "价款", "咨询费总计人民币 150,000 元，合同生效后支付 60%，项目成果验收合格后支付剩余 40%。", 2),
    (70, 112, 11, "第四条", "知识产权", "咨询成果的知识产权归甲方所有；乙方保留方法论与通用工具的使用权，未经甲方许可不得对外披露项目成果。", 2),
]

TASKS = [
    (2001, 1, 102, "diff", None, 1, "completed", 100, "2026-08-26T15:42:00", "2026-08-26T15:43:12", 72000),
    (2002, 2, 103, "full", None, None, "completed", 100, "2026-08-27T10:40:00", "2026-08-27T10:41:22", 82000),
    (2003, 3, 104, "full", None, None, "completed", 100, "2026-08-27T15:50:00", "2026-08-27T15:52:01", 121000),
    (2004, 5, 106, "full", None, None, "running", 65, "2026-08-28T09:10:00", None, None),
    (2005, 12, 109, "clause", "第三条", None, "pending", 0, "2026-08-28T08:50:00", None, None),
    (2006, 7, 108, "diff", None, None, "failed", 40, "2026-08-23T11:02:00", "2026-08-23T11:06:00", None),
]

FINDINGS = [
    dict(id=1, task_id=2001, clause_no="第六条", clause_id=26, level="medium", rtype="违约责任失衡", source="rule",
         issue="甲方逾期付款违约金封顶 5%，而乙方封顶 10%，双方封顶基数不同（合同总价 vs 应付款项），实际权责仍不完全对等。",
         original="乙方逾期交货的……累计不超过合同总价的 10%；甲方逾期付款的……累计不超过应付款项的 5%。",
         basis="《民法典》第五百八十五条：约定的违约金低于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以增加；约定的违约金过分高于造成的损失的，可以请求予以适当减少。",
         suggestion="建议统一违约金计算口径与封顶比例：双方逾期违约金均按日 0.05% 计取，累计均不超过合同总价的 10%，避免基数差异导致实质不公。",
         suggested="乙方逾期交货的，每逾期一日按合同总价的 0.05% 支付违约金，累计不超过合同总价的 10%；甲方逾期付款的，每逾期一日按应付款项的 0.05% 支付违约金，累计不超过合同总价的 10%。",
         rag=["《民法典》第五百八十五条 · 相似度 0.93", "指导案例 64 号：违约金调整纠纷案 · 相似度 0.88", "企业模板 · 违约责任条款（采购 v4）· 相似度 0.85"], status="accepted"),
    dict(id=2, task_id=2001, clause_no="第七条", clause_id=0, level="low", rtype="条款缺失", source="llm",
         issue="v2 版本删除了独立保密条款，商业秘密保护义务缺失，履约中的技术资料与价格信息存在泄露风险。",
         original="（v1 原文：双方对在履约过程中知悉的对方商业秘密负有保密义务，保密期限为合同终止后两年。）",
         basis="企业模板库《服务器采购合同标准模板》v4 - 必备条款「保密条款」：缺失即判定中风险。",
         suggestion="建议恢复保密条款并将保密期限延长至合同终止后三年，或以补充协议形式补签《保密协议》。",
         suggested="双方对在履约过程中知悉的对方商业秘密负有保密义务，保密期限为合同终止后三年。",
         rag=["企业模板 · 保密条款（采购 v4）· 相似度 0.91", "企业模板 · 保密期限条款（保密 v3）· 相似度 0.87"], status="open"),
    dict(id=3, task_id=2001, clause_no="第三条", clause_id=23, level="low", rtype="表述歧义", source="llm",
         issue="「三年上门服务费」未明确响应时限与上门范围，可能与质保条款中的五年整机质保产生衔接歧义。",
         original="合同总价为人民币 860,000 元……包含设备价款、包装费、运输保险费及三年上门服务费。",
         basis="《民法典》第五百一十条：合同生效后，当事人就质量、价款或者报酬、履行地点等内容没有约定或者约定不明确的，可以协议补充。",
         suggestion="建议补充：上门服务响应时限（如 4 小时响应、次工作日到场）、服务范围（全国/指定城市）及与质保期的衔接关系。",
         suggested="合同总价为人民币 860,000 元……包含设备价款、包装费、运输保险费及三年上门服务费（全国范围，4 小时响应、次工作日到场，与五年整机质保期行接）。",
         rag=["《民法典》第五百一十条 · 相似度 0.90", "企业模板 · 售后服务条款（销售 v3）· 相似度 0.84"], status="open"),
    dict(id=4, task_id=2002, clause_no="第七条", clause_id=37, level="low", rtype="表述优化", source="llm",
         issue="知识产权条款中「定制开发成果」未定义边界，实施过程中配置化形成的成果归属可能产生争议。",
         original="软件著作权归乙方所有；基于实施过程形成的定制开发成果，著作权归甲方所有。",
         basis="《民法典》第八百四十三条：技术合同是当事人就技术开发、转让、许可、咨询或者服务订立的确立相互之间权利和义务的合同。",
         suggestion="建议明确定制开发的触发标准（需求变更单/二次开发工时阈值），并约定配置、接口代码与文档的交付形式。",
         suggested="软件著作权归乙方所有；基于双方书面确认的需求变更单、或二次开发工时超过 40 小时形成的定制开发成果（含配置、接口代码与文档），著作权归甲方所有。",
         rag=["《民法典》第八百四十三条 · 相似度 0.89"], status="accepted"),
    dict(id=5, task_id=2002, clause_no="第四条", clause_id=34, level="low", rtype="表述优化", source="rule",
         issue="付款条款未约定发票类型与开具时间，可能影响付款流程与税务处理。",
         original="合同生效后 15 日内支付 40%，系统上线验收后支付 40%，试运行满三个月支付剩余 20%。",
         basis="企业模板库《销售合同标准模板》v3 - 推荐条款「发票约定」。",
         suggestion="建议补充：乙方应于收款前 5 个工作日开具等额增值税专用发票（税率 6%），发票不合规甲方有权暂缓支付。",
         suggested="合同生效后 15 日内支付 40%，系统上线验收后支付 40%，试运行满三个月支付剩余 20%；乙方应于收款前 5 个工作日开具等额增值税专用发票，发票不合规的甲方有权暂缓支付。",
         rag=["企业模板 · 付款条款（采购 v4）· 相似度 0.92", "《民法典》第五百一十条 · 相似度 0.83"], status="open"),
    dict(id=6, task_id=2003, clause_no="第六条", clause_id=45, level="high", rtype="违约责任失衡", source="rule",
         issue="违约责任严重失衡：乙方违约按每人每月费用三倍赔付且无上限，甲方违约封顶仅当月费用 5%；同时甲方享有「随时退回且不承担任何责任」的单方无限权利。",
         original="乙方违约的，按每人每月费用的三倍支付违约金；甲方违约的，赔偿乙方全部损失，违约金不超过当月费用的 5%。",
         basis="《民法典》第五百八十五条：约定的违约金过分高于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以适当减少。",
         suggestion="建议改为对等条款：任一方违约按每人每月费用的 30% 支付违约金，累计均不超过合同总价的 20%；退回派遣人员应提前 7 日书面通知并协商。",
         suggested="任一方违约的，按每人每月费用的 30% 向对方支付违约金，累计不超过合同总价的 20%；甲方退回派遣人员的，应提前 7 日书面通知乙方并协商确定交接事宜。",
         rag=["《民法典》第五百八十五条 · 相似度 0.94", "指导案例 64 号：违约金调整纠纷案 · 相似度 0.90", "《劳动合同法》第五十八条 · 相似度 0.82"], status="open"),
    dict(id=7, task_id=2003, clause_no="第八条", clause_id=46, level="high", rtype="违法无效", source="llm",
         issue="免责条款无效：派遣人员在岗期间的人身损害免责约定，违反法律强制性规定，该条款自始无效，且不能免除用工单位法定安全保障义务。",
         original="乙方派遣人员在岗期间发生的一切人身损害及其他损失，均与甲方无关，甲方不承担任何责任。",
         basis="《民法典》第五百零六条：合同中的下列免责条款无效：（一）造成对方人身损害的；（二）因故意或者重大过失造成对方财产损失的。",
         suggestion="建议删除该免责条款，改为：双方依据《劳动合同法》第五十九条及安全生产法律法规，各自承担相应的安全保障责任与工伤保险义务。",
         suggested="双方依据《劳动合同法》及安全生产法律法规，各自承担相应的安全保障责任与工伤保险义务；因一方过错造成派遣人员损害的，依法承担相应赔偿责任。",
         rag=["《民法典》第五百零六条 · 相似度 0.95", "《民法典》第四百九十七条 · 相似度 0.87"], status="open"),
    dict(id=8, task_id=2003, clause_no="第十条", clause_id=47, level="medium", rtype="权责不对等", source="llm",
         issue="验收标准由甲方单方解释并认定，乙方对验收结果无申辩机制，构成显失公平的单方解释权条款。",
         original="派遣人员工作质量的验收标准由甲方单方解释并认定。",
         basis="《民法典》第四百九十六条：采用格式条款订立合同的，提供格式条款的一方应当遵循公平原则确定当事人之间的权利和义务。",
         suggestion="建议改为：验收标准以双方确认的《岗位工作标准》为准；有异议的，由双方负责人在 3 个工作日内复核确认。",
         suggested="派遣人员工作质量的验收标准以双方确认的《岗位工作标准》为准；一方对验收结果有异议的，由双方负责人在 3 个工作日内复核确认。",
         rag=["《民法典》第四百九十六条 · 相似度 0.91"], status="open"),
    dict(id=9, task_id=2003, clause_no="第十二条", clause_id=48, level="medium", rtype="表述歧义", source="rule",
         issue="保密期限约定为「直至公开为止」，属于不确定期限，实践中易引发争议，且未约定违约金计算方式。",
         original="双方对知悉的商业秘密保密，保密期直至公开为止。",
         basis="企业模板库《劳务派遣合同标准模板》v2 - 必备条款「保密条款」。",
         suggestion="建议改为：保密期限为合同终止后五年；违反保密义务的，按违约行为给对方造成实际损失赔偿，并另行支付违约金 10 万元。",
         suggested="双方对知悉的商业秘密保密，保密期限为合同终止后五年；违反保密义务的，按违约行为给对方造成的实际损失赔偿，并另行支付违约金人民币 10 万元。",
         rag=["企业模板 · 保密与竞业限制条款（劳务 v2）· 相似度 0.90", "企业模板 · 违约责任条款（保密 v3）· 相似度 0.86"], status="open"),
]

REPORTS = [
    (1, 2001, 1, "建议修改后签署：v2 修订版整体风险可控（无高风险），但违约金封顶口径不对等、保密条款缺失两项问题建议在签署前修订；评分 75 分未达 85 分审批线，修订后可申请增量重审。"),
    (2, 2002, 2, "建议签署：全文审查未发现高风险与中风险问题，2 项低风险优化建议（知识产权边界、发票约定）可在实施阶段以补充协议方式完善，评分 90 分已满足审批发起条件。"),
    (3, 2003, 3, "不建议签署：存在 2 项高风险（违约责任严重失衡、人身损害免责条款无效），已触发高风险阻断机制，必须修改后重新送审；另有 2 项中风险需一并修订。"),
]

WF_DEFINITIONS = [
    {
        "id": 1, "name": "标准合同审批流", "contract_types": ["purchase", "sales", "labor", "lease", "nda", "other"],
        "version": 3, "enabled": True, "updated": "2026-08-15T10:00:00",
        "nodes": [
            {"id": "start", "type": "start", "name": "发起", "assignees": ["role:business_owner"]},
            {"id": "n1", "type": "approval", "name": "部门经理审批", "signMode": "or", "assignees": ["role:dept_manager"], "timeoutHours": 24},
            {"id": "n2", "type": "condition", "name": "高风险判断", "rules": [
                {"when": "risk_score < 85 or amount >= 1000000", "goto": "n3"},
                {"when": "default", "goto": "cc1"},
            ]},
            {"id": "n3", "type": "approval", "name": "法务加签", "signMode": "and", "assignees": ["user:lihuimin"], "timeoutHours": 48},
            {"id": "cc1", "type": "cc", "name": "抄送审计", "assignees": ["role:auditor"]},
            {"id": "end", "type": "end", "name": "通过签署", "result": "approved"},
        ],
        "edges": [
            {"from": "start", "to": "n1"}, {"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"},
            {"from": "n2", "to": "cc1"}, {"from": "n3", "to": "cc1"}, {"from": "cc1", "to": "end"},
        ],
    },
    {
        "id": 2, "name": "小额合同快捷审批流", "contract_types": ["other", "purchase"], "version": 1, "enabled": True,
        "updated": "2026-08-20T14:00:00",
        "nodes": [
            {"id": "start", "type": "start", "name": "发起", "assignees": ["role:business_owner"]},
            {"id": "m1", "type": "approval", "name": "部门主管审批", "signMode": "or", "assignees": ["role:dept_manager"], "timeoutHours": 12},
            {"id": "end", "type": "end", "name": "通过签署", "result": "approved"},
        ],
        "edges": [{"from": "start", "to": "m1"}, {"from": "m1", "to": "end"}],
    },
]

WF_INSTANCES = [
    dict(id=1, def_id=1, def_name="标准合同审批流", def_ver=3, contract_id=1, node="n3", node_name="法务加签",
         status="running", snapshot={"score": 75, "amount": 860000, "highRisk": 0, "riskTotal": 3},
         starter_id=4, starter="王晓东", started="2026-08-26T16:00:00", finished=None,
         records=[
             (1, "start", "发起", "submit", "王晓东", "v2 修订版已完成增量审查，评分 75 分（低于 85 分线），按流程转入法务加签，请审阅。", "2026-08-26T16:00:00"),
             (2, "n1", "部门经理审批", "approve", "周伟民", "业务侧无异议，同意进入法务复核。", "2026-08-27T09:20:00"),
             (3, "n2", "高风险判断", "approve", "系统", "规则命中：risk_score(75) < 85 → 流转至「法务加签」节点。", "2026-08-27T09:20:01"),
         ]),
    dict(id=2, def_id=2, def_name="小额合同快捷审批流", def_ver=1, contract_id=4, node="m1", node_name="部门主管审批",
         status="running", snapshot={"score": 92, "amount": 540000, "highRisk": 0, "riskTotal": 1},
         starter_id=7, starter="刘洋", started="2026-08-26T10:15:00", finished=None,
         records=[(4, "start", "发起", "submit", "刘洋", "场地租赁合同已通过 AI 审查（92 分），申请审批。", "2026-08-26T10:15:00")]),
    dict(id=3, def_id=1, def_name="标准合同审批流", def_ver=2, contract_id=9, node="end", node_name="通过签署",
         status="approved", snapshot={"score": 95, "amount": 265000, "highRisk": 0, "riskTotal": 1},
         starter_id=4, starter="王晓东", started="2026-08-22T11:00:00", finished="2026-08-25T14:00:00",
         records=[
             (5, "start", "发起", "submit", "王晓东", "年度维保合同续签，审查 95 分。", "2026-08-22T11:00:00"),
             (6, "n1", "部门经理审批", "approve", "周伟民", "同意。", "2026-08-23T09:00:00"),
             (7, "cc1", "抄送审计", "approve", "系统", "已抄送审计员赵建国。", "2026-08-23T09:00:01"),
             (8, "end", "通过签署", "approve", "系统", "流程终审通过，合同进入签署归档。", "2026-08-25T14:00:00"),
         ]),
    dict(id=4, def_id=1, def_name="标准合同审批流", def_ver=2, contract_id=10, node="end", node_name="已否决",
         status="rejected", snapshot={"score": 40, "amount": 188000, "highRisk": 0, "riskTotal": 4},
         starter_id=7, starter="刘洋", started="2026-08-20T09:30:00", finished="2026-08-24T09:50:00",
         records=[
             (9, "start", "发起", "submit", "刘洋", "冷链运输年度合同，请审批。", "2026-08-20T09:30:00"),
             (10, "n1", "部门经理审批", "approve", "周伟民", "业务需要，同意上报。", "2026-08-21T10:00:00"),
             (11, "n3", "法务加签", "reject", "李慧敏", "运输责任限额条款对生鲜货损覆盖率不足，赔偿上限过低，建议重新谈判后重报。", "2026-08-24T09:50:00"),
         ]),
    dict(id=5, def_id=2, def_name="小额合同快捷审批流", def_ver=1, contract_id=12, node="m1", node_name="部门主管审批",
         status="withdrawn", snapshot={"score": 95, "amount": 46000, "highRisk": 0, "riskTotal": 0},
         starter_id=7, starter="刘洋", started="2026-08-27T11:00:00", finished="2026-08-27T14:30:00",
         records=[
             (12, "start", "发起", "submit", "刘洋", "办公用品季度采购，审查 95 分。", "2026-08-27T11:00:00"),
             (13, "start", "发起", "withdraw", "刘洋", "价格清单附件上传有误，撤回重新发起。", "2026-08-27T14:30:00"),
         ]),
]

AUDITS = [
    (1, "zhangmy", "login", "会话", "-", {"ip": "192.168.1.23", "ua": "Chrome 126 / Windows 11", "result": "成功"}, "2026-08-28T09:00:00"),
    (2, "wangxd", "contract.upload", "合同", "HT-2026-0006", {"ip": "192.168.1.41", "ua": "Edge 126 / Windows 11", "result": "成功", "extra": "文件指纹 SHA-256: 3f2a…c8d1，大小 3.1MB"}, "2026-08-28T08:30:00"),
    (3, "liuyang", "contract.download", "合同", "HT-2026-0004", {"ip": "192.168.1.52", "ua": "Chrome 126 / macOS 14", "result": "成功", "extra": "版本 v1"}, "2026-08-27T16:20:00"),
    (4, "zhangmy", "review.start", "审查任务", "2004", {"ip": "192.168.1.23", "ua": "Chrome 126 / Windows 11", "result": "成功", "extra": "任务类型 full，模型 deepseek-v4-flash-vision-exp，Prompt v1.3"}, "2026-08-28T09:10:00"),
    (5, "admin", "review.export", "审查报告", "R-2002", {"ip": "192.168.1.10", "ua": "Chrome 126 / Windows 11", "result": "成功", "extra": "导出 PDF"}, "2026-08-27T14:05:00"),
    (6, "zhouwm", "workflow.approve", "流程实例", "1", {"ip": "192.168.1.35", "ua": "WeChat Work / Windows", "result": "成功", "extra": "节点 n1 部门经理审批"}, "2026-08-27T09:20:00"),
    (7, "lihuimin", "workflow.reject", "流程实例", "4", {"ip": "192.168.1.22", "ua": "Chrome 126 / Windows 11", "result": "成功", "extra": "节点 n3 法务加签，意见：赔偿上限过低"}, "2026-08-24T09:50:00"),
    (8, "admin", "system.role.update", "角色", "legal_reviewer", {"ip": "192.168.1.10", "ua": "Chrome 126 / Windows 11", "result": "成功", "extra": "新增权限点 knowledge:manage"}, "2026-08-26T10:30:00"),
    (9, "liuyang", "workflow.withdraw", "流程实例", "5", {"ip": "192.168.1.52", "ua": "Chrome 126 / macOS 14", "result": "成功", "extra": "撤回原因：附件上传有误"}, "2026-08-27T14:30:00"),
    (10, "unknown_user", "login", "会话", "-", {"ip": "10.20.30.99", "ua": "curl/8.4.0", "result": "失败", "extra": "密码错误 3 次，账号已临时锁定 15 分钟"}, "2026-08-27T22:10:00"),
    (11, "zhangmy", "finding.accept", "风险发现", "F-4", {"ip": "192.168.1.23", "ua": "Chrome 126 / Windows 11", "result": "成功", "extra": "采纳建议：明确定制开发边界"}, "2026-08-27T11:40:00"),
    (12, "admin", "knowledge.import", "法律法规", "batch-20260826", {"ip": "192.168.1.10", "ua": "Chrome 126 / Windows 11", "result": "成功", "extra": "Excel 批量导入 42 条，向量化完成 42/42"}, "2026-08-26T09:00:00"),
    (13, "wangxd", "contract.archive", "合同", "HT-2026-0011", {"ip": "192.168.1.41", "ua": "Edge 126 / Windows 11", "result": "成功", "extra": "归档策略：审批完成自动归档"}, "2026-08-10T16:30:00"),
    (14, "sunqian", "review.rerun", "审查任务", "2001", {"ip": "192.168.1.31", "ua": "Chrome 126 / Windows 11", "result": "成功", "extra": "v2 增量重审（diff 模式）"}, "2026-08-26T15:42:00"),
    (15, "zhangmy", "login", "会话", "-", {"ip": "192.168.1.23", "ua": "Chrome 126 / Windows 11", "result": "成功"}, "2026-08-27T08:55:00"),
    (16, "admin", "system.user.disable", "用户", "wufa", {"ip": "192.168.1.10", "ua": "Chrome 126 / Windows 11", "result": "成功", "extra": "离职账号停用（数据保留 ≥ 3 年）"}, "2026-07-01T09:00:00"),
]

NOTIFICATIONS = [
    (1, "approval_todo", "法务加签待办", "「服务器设备采购合同（二期扩容）」已流转至法务加签节点，请在 48 小时内处理。", False, "2026-08-27T09:20:01"),
    (2, "approval_timeout", "审批超时催办", "「办公楼三层场地租赁合同」在节点「部门主管审批」停留已超过 24 小时（限时 12 小时），已发送催办提醒。", False, "2026-08-27T10:20:00"),
    (3, "review_done", "AI 审查完成", "「MES 制造执行系统销售合同」全文审查完成：90 分，0 高风险，可发起审批。", False, "2026-08-27T10:41:22"),
    (4, "review_done", "AI 审查完成（高风险阻断）", "「劳务派遣服务合同」全文审查完成：发现 2 项高风险，已阻断进入审批，请修改后重审。", True, "2026-08-27T15:52:01"),
    (5, "approval_todo", "审批待办提醒", "「生产设备年度维护服务合同」已终审通过并归档，点击查看审批记录。", True, "2026-08-25T14:00:00"),
]

MODEL_VERSIONS = [
    (1, "deepseek-v4-flash-vision-exp", "llm", True, {"accuracy": 0.94, "falsePositive": 0.06, "adoptionRate": 0.87}, "2026-08-01T09:00:00"),
    (2, "deepseek-v4-flash（降级备用）", "llm", False, {"accuracy": 0.93, "falsePositive": 0.07, "adoptionRate": 0.85}, "2026-07-15T09:00:00"),
    (3, "text-embedding-v4 (1024d)", "embedding", True, {"accuracy": 0.91, "falsePositive": 0.04, "adoptionRate": None}, "2026-07-10T09:00:00"),
    (4, "text-embedding-v3 (1024d)", "embedding", False, {"accuracy": 0.88, "falsePositive": 0.05, "adoptionRate": None}, "2026-05-20T09:00:00"),
]

PROMPTS = [
    (1, "v1.3", "条款合规审查", True, "2026-08-20T10:00:00",
     "[角色]\n你是资深企业法务合规审查专家，熟悉《民法典》合同编及中国合同实务。\n\n[审查对象]\n合同类型：{contract_type}\n待审条款：\n{clause_text}\n\n[参考依据]（检索自知识库，仅供引用，不得编造）\n{rag_context}\n\n[输出要求]\n仅输出 JSON，不要输出任何其他文字，结构如下：\n{\n  \"risk_level\": \"high | medium | low | none\",\n  \"risk_type\": \"风险类型（如 违约责任失衡/条款缺失/违法无效）\",\n  \"risk_points\": [\n    {\n      \"original_text\": \"原文摘录\",\n      \"issue\": \"风险描述\",\n      \"legal_basis\": \"引用上述参考依据的条文编号，未命中则填 null\",\n      \"suggestion\": \"具体改写建议\",\n      \"suggested_text\": \"按建议改写后的完整条款文本\"\n    }\n  ]\n}"),
    (2, "v1.2", "条款合规审查", False, "2026-07-18T10:00:00",
     "[角色]\n你是企业法务合规审查专家。\n\n[审查对象]\n合同类型：{contract_type}\n待审条款：{clause_text}\n\n[参考依据]\n{rag_context}\n\n[输出要求]\n仅输出 JSON：{ \"risk_level\": \"...\", \"risk_points\": [...] }"),
    (3, "v1.0", "扫描件视觉解析", True, "2026-07-10T10:00:00",
     "识别本页合同图片中的全部条款文本，按条款号结构化输出 JSON（包含 clause_no / clause_type / content / page_no），不要输出任何其他文字。"),
    (4, "v1.1", "版本差异归纳", True, "2026-08-05T10:00:00",
     "对比以下新旧条款，归纳差异类型（新增/删除/修改/语义漂移）并输出一句话差异说明：\n旧条款：{old_clause}\n新条款：{new_clause}\n仅输出 JSON：{ \"kind\": \"added | removed | modified | drift\", \"summary\": \"...\" }"),
]


def seed():
    db = SessionLocal()
    try:
        if db.query(User).count() > 0 and not RESET:
            harden_legacy_accounts(db, bootstrap_password=settings.bootstrap_admin_password)
            sync_permissions(db)
            seed_preset_accounts(db)  # Old DBs also need preset accounts seeded/revoked per the switch
            migrate_legacy_reports(db)
            print("[3/7] 已存在数据，完成安全升级后跳过演示数据写入")
            return

        validate_password(settings.bootstrap_admin_password)

        # Permissions
        perm_map = {}
        for code, name, module in PERMISSIONS:
            p = Permission(code=code, name=name, module=module)
            db.add(p)
            perm_map[code] = p
        db.flush()

        # Roles
        role_map = {}
        for code, name, desc, scope, perms in ROLES:
            r = Role(code=code, name=name, description=desc, data_scope=scope)
            r.permissions = [perm_map[c] for c in sorted(set(perms) | UPGRADE_GRANTS.get(code, set()))]
            db.add(r)
            role_map[code] = r
        db.flush()

        # Admins are always enabled and must change password on first login; preset accounts are
        # enabled only when PRESET_ACCOUNTS_ENABLED is on, otherwise a random unusable password is
        # written and the account is disabled (re-enabled by an admin on demand).
        preset_password = effective_password()
        for account in USERS:
            roles = account.roles
            is_admin = "admin" in roles
            if is_admin:
                password, must_change, active = settings.bootstrap_admin_password, True, account.active
            elif preset_password:
                password, must_change, active = preset_password, False, account.active
            else:
                password, must_change, active = secrets.token_urlsafe(32), True, False
            u = User(
                username=account.username,
                password_hash=hash_password(password),
                must_change_password=must_change,
                real_name=account.real_name,
                dept_name=account.dept_name,
                title=account.title,
                phone=account.phone,
                is_active=active,
                last_login_at=dt(account.last_login),
                created_at=datetime(2026, 6, 1),
            )
            u.roles = [role_map[c] for c in roles]
            db.add(u)
        db.flush()
        if preset_password:
            print("[3/7] 权限/角色/用户已写入；管理员使用 BOOTSTRAP_ADMIN_PASSWORD（首次登录须改密）；"
                  "预制账号已启用并统一使用 PRESET_ACCOUNT_PASSWORD")
        else:
            print("[3/7] 权限/角色/用户已写入；管理员使用 BOOTSTRAP_ADMIN_PASSWORD，首次登录须改密；"
                  "预制账号已停用（PRESET_ACCOUNTS_ENABLED=false）")

        # Laws and templates
        for doc_type, title, content, source_ref, eff, exp, status, _vec, hit in LAWS:
            db.add(LawRegulation(
                doc_type=doc_type, title=title, content=content, source_ref=source_ref,
                effective_date=d(eff), expiry_date=d(exp) if exp else None,
                status=status, vectorized=False, hit_count=hit,  # The vectorized flag is decided by the ES ingestion step
                created_at=datetime(2026, 8, 1),
            ))
        for tid, name, ctype, level, content, ver in TEMPLATES:
            db.add(ContractTemplate(
                id=tid, name=name, contract_type=ctype, clause_level=level, content=content,
                version=ver, vectorized=False, created_at=datetime(2026, 7, 1), updated_at=datetime(2026, 8, 15),
            ))
        db.flush()
        print("[4/7] 法规库 17 条 / 模板条款 24 条 已写入")

        # Contracts / versions / clauses
        for cid, no, title, ctype, owner_id, _x, status, ver, cp_name, cp_idno, cp_phone, amount, created, updated in CONTRACTS:
            db.add(Contract(
                id=cid, contract_no=no, title=title, contract_type=ctype, owner_id=owner_id, status=status,
                current_version=ver, file_sha256=None,
                counterparty_name=cp_name, counterparty_id_no_enc=encrypt_text(cp_idno),
                counterparty_phone_enc=encrypt_text(cp_phone), amount=amount,
                created_at=dt(created), updated_at=dt(updated),
            ))
        db.flush()
        for vid, cid, ver, parent, fname, size_kb, pstatus, channel, created in VERSIONS:
            db.add(ContractVersion(
                id=vid, contract_id=cid, version_no=ver, parent_id=parent, file_name=fname,
                file_path=None, file_size_kb=size_kb, parse_status=pstatus,
                parse_channel=channel, created_at=dt(created),
            ))
        db.flush()
        for cl_id, vid, cid, no, ctype, content, page in CLAUSES:
            db.add(ContractClause(
                id=cl_id, version_id=vid, contract_id=cid, clause_no=no, clause_type=ctype,
                content=content, page_no=page, char_start=0, char_end=len(content),
            ))
        db.flush()
        print("[5/7] 合同 12 / 版本 12 / 条款 已写入（状态覆盖 11 态）")

        # Review tasks / risk findings / reports
        for tid, cid, vid, ttype, clause_no, base_ver, status, progress, created, completed, duration in TASKS:
            tokens = {2001: 18650, 2002: 21450, 2003: 26400}.get(tid)
            db.add(ReviewTask(
                id=tid, contract_id=cid, version_id=vid, task_type=ttype, clause_no=clause_no,
                base_version_no=base_ver, status=status, progress=progress,
                model_version="deepseek-v4-flash-vision-exp", prompt_version="v1.3",
                task_key=f"seed:{tid}",
                error_msg="视觉模型连续 3 次响应超时（指数退避后仍失败），已降级标记待人工录入" if tid == 2006 else None,
                created_at=dt(created), completed_at=dt(completed) if completed else None,
                duration_ms=duration, tokens_used=tokens,
            ))
        db.flush()
        for f in FINDINGS:
            db.add(RiskFinding(
                id=f["id"], task_id=f["task_id"], clause_id=f["clause_id"], clause_no=f["clause_no"],
                risk_level=f["level"], risk_type=f["rtype"], issue=f["issue"], original_text=f["original"],
                legal_basis=f["basis"], suggestion=f["suggestion"], suggested_text=f["suggested"],
                rag_hits=f["rag"], source=f["source"], status=f["status"], created_at=datetime(2026, 8, 27, 12, 0),
            ))
        db.flush()
        for rid, task_id, cid, opinion in REPORTS:
            fs = [f for f in FINDINGS if f["task_id"] == task_id]
            high = sum(1 for f in fs if f["level"] == "high")
            medium = sum(1 for f in fs if f["level"] == "medium")
            low = sum(1 for f in fs if f["level"] == "low")
            score = max(0, 100 - 40 * high - 15 * medium - 5 * low)
            db.add(ReviewReport(
                id=rid, task_id=task_id, contract_id=cid, score=score,
                high_count=high, medium_count=medium, low_count=low,
                overall_opinion=opinion,
                report_json={"summary": {"high": high, "medium": medium, "low": low, "score": score},
                             "overallOpinion": opinion},
                created_at=dt("2026-08-27T16:00:00"),
            ))
        print("[6/7] 审查任务 6 / 风险发现 9 / 审查报告 3 已写入")

        # Workflow
        for wd in WF_DEFINITIONS:
            db.add(WorkflowDefinition(
                id=wd["id"], name=wd["name"], contract_types=wd["contract_types"],
                graph={"nodes": wd["nodes"], "edges": wd["edges"]}, version=wd["version"],
                enabled=wd["enabled"], updated_at=dt(wd["updated"]), created_at=datetime(2026, 8, 1),
            ))
        db.flush()
        for inst in WF_INSTANCES:
            db.add(WorkflowInstance(
                id=inst["id"], definition_id=inst["def_id"], definition_name=inst["def_name"],
                definition_version=inst["def_ver"], contract_id=inst["contract_id"],
                current_node_id=inst["node"], current_node_name=inst["node_name"], status=inst["status"],
                context_snapshot=inst["snapshot"], node_state={},
                starter_id=inst["starter_id"], starter_name=inst["starter"],
                started_at=dt(inst["started"]), finished_at=dt(inst["finished"]) if inst["finished"] else None,
            ))
        db.flush()
        for inst in WF_INSTANCES:
            for rid, node, node_name, action, operator, comment, created in inst["records"]:
                db.add(ApprovalRecord(
                    id=rid, instance_id=inst["id"], node_id=node, node_name=node_name, action=action,
                    operator_id=0, operator_name=operator, comment=comment, created_at=dt(created),
                ))
        db.flush()

        # Audit / notifications / model versions / Prompt
        for aid, username, action, rtype, rid, detail, created in AUDITS:
            db.add(AuditLog(id=aid, user_id=None, username=username, action=action,
                            resource_type=rtype, resource_id=rid, detail=detail, created_at=dt(created)))
        for nid, ntype, title, content, read, created in NOTIFICATIONS:
            db.add(Notification(id=nid, type=ntype, title=title, content=content, read=read, created_at=dt(created)))
        for mid, name, mtype, is_default, metrics, activated in MODEL_VERSIONS:
            db.add(ModelVersion(id=mid, model_name=name, model_type=mtype, is_default=is_default,
                                eval_metrics=metrics, activated_at=dt(activated)))
        for pid, ver, scene, active, updated, content in PROMPTS:
            db.add(PromptTemplate(id=pid, version=ver, scene=scene, content=content,
                                  is_active=active, updated_at=dt(updated)))
        db.commit()
        print("      流程定义 2 / 实例 5 / 审批记录 13 / 审计 16 / 通知 5 / 模型 4 / Prompt 4 已写入")
    finally:
        db.close()


def seed_es():
    """Create ES indices and vectorize seed laws/templates (real BaiLian API; failures mark vectorized=false without blocking)."""
    try:
        from app.es.indices import delete_indices, ensure_indices

        if RESET:
            delete_indices()
        ok = ensure_indices()
        if not ok:
            print("[7/7] ES 不可用，跳过向量化（检索功能将返回空结果）")
            return
    except Exception as e:
        print(f"[7/7] ES 索引初始化失败：{e}")
        return

    from app.ai.providers import ModelConfigError, embedding_endpoint

    try:
        _embedding = embedding_endpoint()
    except ModelConfigError as e:
        print(f"[7/7] 向量模型配置错误，跳过向量化：{e}")
        return
    if _embedding.requires_api_key and not _embedding.api_key:
        print(f"[7/7] 未配置 {_embedding.api_key_env}（厂商 {_embedding.provider}），跳过向量化（vectorized=false）")
        return
    print(f"[7/7] 向量模型：{_embedding.label}（{_embedding.dimensions}d）")

    from app.services import knowledge_service

    db = SessionLocal()
    ok_n = fail_n = 0
    try:
        laws = db.query(LawRegulation).all()
        for law in laws:
            if knowledge_service.index_law(db, law):
                ok_n += 1
            else:
                fail_n += 1
        tpls = db.query(ContractTemplate).all()
        for tpl in tpls:
            knowledge_service.index_template(db, tpl)
        print(f"[7/7] ES 索引就绪；法条向量化 {ok_n} 成功 / {fail_n} 失败；模板条款向量化已提交（真实百炼 API）")
    except Exception as e:
        print(f"[7/7] 向量化中断：{e}（已成功的条目保持 vectorized=true）")
    finally:
        db.close()


if __name__ == "__main__":
    settings.validate_security()
    print("=" * 56)
    print("AI智能合同合规审查平台 · 数据库初始化")
    print("=" * 56)
    create_database()
    create_tables()
    seed()
    seed_es()
    print("完成。启动方式：uvicorn app.main:app --host 0.0.0.0 --port 8000")
