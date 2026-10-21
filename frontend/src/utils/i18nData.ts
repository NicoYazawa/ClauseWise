import { i18n } from '@/i18n'

/**
 * Dictionary-style fields returned by the backend are still Chinese constants
 * (role names / departments / workflow nodes / agent roles / audit results).
 * Without changing the API contract, this builds a reverse map from the raw
 * Chinese value to an i18n key. Unmapped values fall back as-is, so a new enum
 * added on the backend will not blank out the UI - it just keeps its Chinese text.
 */
const REVERSE_MAP: Record<string, string> = {
  // Roles
  系统管理员: 'data.role.admin',
  法务主管: 'data.role.legal',
  法务审查员: 'data.role.reviewer',
  业务经办人: 'data.role.operator',
  审计员: 'data.role.auditor',
  部门经理: 'data.role.manager',
  // Departments
  法务部: 'data.dept.legal',
  采购部: 'data.dept.procurement',
  销售部: 'data.dept.sales',
  审计部: 'data.dept.audit',
  信息管理部: 'data.dept.it',
  财务部: 'data.dept.finance',
  // Workflow nodes
  发起: 'data.node.start',
  部门经理审批: 'data.node.deptManager',
  部门主管审批: 'data.node.deptSupervisor',
  法务加签: 'data.node.legalCountersign',
  抄送审计: 'data.node.ccAudit',
  高风险判断: 'data.node.highRiskCheck',
  // End nodes are fixed and written by the backend (workflows.py / workflow_engine.py)
  通过签署: 'data.node.signEnd',
  已否决: 'data.node.rejectedEnd',
  结束: 'data.node.endFallback',
  条件判断: 'data.node.conditionFallback',
  抄送: 'data.node.ccFallback',
  // Workflow definitions (default seed-data names; user-defined names are outside the map and shown as-is)
  标准合同审批流: 'data.definition.standard',
  // Agent roles
  规划者: 'data.agentRole.planner',
  规则审计员: 'data.agentRole.ruleAuditor',
  条款审查员: 'data.agentRole.clauseReviewer',
  复核员: 'data.agentRole.verifier',
  报告撰写员: 'data.agentRole.reporter',
  意图路由: 'data.agentRole.intentRouter',
  查询规划: 'data.agentRole.queryPlanner',
  检索执行: 'data.agentRole.retriever',
  检索质量评估: 'data.agentRole.grader',
  'CRAG 纠错': 'data.agentRole.corrector',
  答案生成: 'data.agentRole.answerer',
  'SelfRAG 反思': 'data.agentRole.reflector',
  // Audit results
  成功: 'data.result.success',
  失败: 'data.result.fail',
}

/** Render backend dictionary fields in the active language; fall back to the raw value if not mapped */
export function translateData(raw: string | null | undefined): string {
  if (!raw) return ''
  const key = REVERSE_MAP[raw]
  return key ? i18n.global.t(key) : raw
}
