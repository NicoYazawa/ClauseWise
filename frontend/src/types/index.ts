// ===================== Base enums =====================

/** Contract type: purchase / sales / labor / lease / NDA / other */
export type ContractType = 'purchase' | 'sales' | 'labor' | 'lease' | 'nda' | 'other'

/** Contract state machine (design doc 3.3.3, 11 states total) */
export type ContractStatus =
  | 'draft'
  | 'parsing'
  | 'parsed'
  | 'parse_failed'
  | 'under_review'
  | 'review_passed'
  | 'review_blocked'
  | 'in_approval'
  | 'approved'
  | 'rejected'
  | 'archived'

/** Parse channel */
export type ParseChannel = 'text' | 'vision' | 'mixed'

/** Version parse status */
export type ParseStatus = 'pending' | 'parsing' | 'parsed' | 'failed'

/** Review task type: full-text / single-clause / incremental */
export type ReviewTaskType = 'full' | 'clause' | 'diff'

/** Review task status */
export type ReviewTaskStatus = 'pending' | 'running' | 'completed' | 'failed'

/** Risk level */
export type RiskLevel = 'high' | 'medium' | 'low'

/** Risk source (dual-track verification): rule engine / LLM RAG */
export type FindingSource = 'rule' | 'llm'

/** Risk disposition status */
export type FindingStatus = 'open' | 'accepted' | 'rejected' | 'fixed'

/** Workflow instance status */
export type WorkflowStatus = 'running' | 'approved' | 'rejected' | 'withdrawn'

/** Approval action (incl. flow initiation submit & urging urge) */
export type ApprovalAction = 'submit' | 'approve' | 'reject' | 'return' | 'withdraw' | 'urge'

/** Workflow node type */
export type WFNodeType = 'start' | 'approval' | 'condition' | 'cc' | 'end'

/** Sign-off mode */
export type SignMode = 'or' | 'and' | 'sequence'

// ===================== Contract domain =====================

export interface Counterparty {
  name: string
  /** ID number (masked on display) */
  idNo: string
  /** Phone number (masked on display) */
  phone: string
}

export interface Contract {
  id: number
  contractNo: string
  title: string
  contractType: ContractType
  ownerId: number
  ownerName: string
  status: ContractStatus
  currentVersion: number
  counterparty: Counterparty
  /** Contract amount (CNY) */
  amount: number
  createdAt: string
  updatedAt: string
}

export interface ContractVersion {
  id: number
  contractId: number
  versionNo: number
  parentId: number | null
  fileName: string
  fileSizeKb: number
  parseStatus: ParseStatus
  parseChannel: ParseChannel | null
  createdAt: string
}

export interface ContractClause {
  id: number
  versionId: number
  contractId: number
  clauseNo: string
  clauseType: string
  content: string
  pageNo: number
}

/** Clause-level diff kind (aligns with design doc 3.1.4 semantic diff output) */
export type ClauseDiffKind = 'added' | 'removed' | 'modified' | 'drift'

export interface ClauseDiffItem {
  clauseNo: string
  kind: ClauseDiffKind
  /** Old version text */
  oldText: string
  /** New version text */
  newText: string
  /** AI diff summarization note */
  summary: string
}

// ===================== AI review domain =====================

export interface ReviewTask {
  id: number
  contractId: number
  contractTitle: string
  taskType: ReviewTaskType
  /** clause type: the target clause number under review */
  clauseNo?: string | null
  status: ReviewTaskStatus
  /** 0-100, polled & displayed on the frontend */
  progress: number
  modelVersion: string
  promptVersion: string
  errorMsg: string | null
  createdAt: string
  completedAt: string | null
  /** Duration in milliseconds */
  durationMs: number | null
}

/** Risk finding five-tuple (3.2.2) */
export interface RiskFinding {
  id: number
  taskId: number
  clauseNo: string
  clauseId: number
  riskLevel: RiskLevel
  riskType: string
  /** Risk description */
  issue: string
  /** Original text excerpt */
  originalText: string
  /** Legal/template basis (RAG hit source) */
  legalBasis: string
  /** Full remediation suggestion */
  suggestion: string
  /** Rewritten clause text (for original/suggestion char-level diff, 3.2.5) */
  suggestedText?: string
  /** RAG-hit knowledge items (title + similarity; conclusions traceable, 3.2.1) */
  ragHits?: string[]
  source: FindingSource
  status: FindingStatus
  /** Whether the revised clause was auto-backfilled on acceptance (returned by the backend disposition API; after refresh shown as status=fixed) */
  applied?: boolean
}

export interface ReportSummary {
  high: number
  medium: number
  low: number
  /** Compliance score = 100 - 40H - 15M - 5L (rule-engine basis only), floored at 0 */
  score: number
  /** Rule-engine blocking items: score & approval threshold use only these; AI reference findings don't block */
  blockingHigh: number
  aiHigh?: number
  aiMedium?: number
  aiLow?: number
  /** > 0 = some clauses were skipped (incomplete report; cannot authorize approval) */
  failedClauses?: number
  /** true = content/version changed or legacy unbound report; must re-review before approval */
  needsReReview?: boolean
  /** full / clause / diff — only a full review can authorize whole-contract approval */
  taskType?: string
}

export interface ReportMeta {
  model: string
  promptVersion: string
  tokensUsed: number
  durationMs: number
}

export interface ReviewReport {
  id: number
  taskId: number
  contractId: number
  summary: ReportSummary
  overallOpinion: string
  findings: RiskFinding[]
  meta: ReportMeta
  createdAt: string
}

// ===================== Approval workflow domain =====================

export interface WFNode {
  id: string
  type: WFNodeType
  name: string
  signMode?: SignMode
  assignees?: string[]
  timeoutHours?: number
  /** Condition node rule expression */
  rules?: { when: string; goto: string }[]
  result?: 'approved' | 'rejected' | 'withdrawn'
}

export interface WorkflowDefinition {
  id: number
  name: string
  contractTypes: ContractType[]
  nodes: WFNode[]
  edges: { from: string; to: string }[]
  version: number
  enabled: boolean
  updatedAt: string
}

export interface ContextSnapshot {
  score: number
  amount: number
  highRisk: number
  riskTotal: number
}

export interface ApprovalRecord {
  id: number
  instanceId: number
  nodeId: string
  nodeName: string
  action: ApprovalAction
  operatorName: string
  comment: string
  createdAt: string
}

export interface WorkflowInstance {
  id: number
  definitionId: number
  definitionName: string
  definitionVersion: number
  contractId: number
  contractTitle: string
  currentNodeId: string
  currentNodeName: string
  status: WorkflowStatus
  contextSnapshot: ContextSnapshot
  starterName: string
  startedAt: string
  finishedAt: string | null
  records: ApprovalRecord[]
}

// ===================== Knowledge base domain =====================

export interface LawRegulation {
  id: number
  docType: 'law' | 'case'
  title: string
  content: string
  sourceRef: string
  effectiveDate: string
  expiryDate: string | null
  status: 'active' | 'expired'
  /** Vectorization / ingestion status */
  vectorized: boolean
  /** RAG hit count */
  hitCount: number
}

export interface ContractTemplate {
  id: number
  name: string
  contractType: ContractType
  clauseLevel: 'required' | 'recommended' | 'optional'
  content: string
  version: number
}

// ===================== User & permission domain =====================

export interface RoleInfo {
  code: string
  name: string
  description: string
  permissions: string[]
  dataScope: 'self' | 'dept' | 'all'
}

export interface User {
  id: number
  username: string
  realName: string
  deptName: string
  title: string
  /** Already masked by backend (mask_phone); middle four digits shown as * */
  phone: string
  roles: string[]
  isActive: boolean
  lastLoginAt: string
  mustChangePassword: boolean
}

export interface TemporaryCredentialUser extends User {
  temporaryPassword: string
  mustChangePassword: true
}

export interface AuditLog {
  id: number
  username: string
  action: string
  resourceType: string
  resourceId: string
  detail: {
    ip: string
    ua: string
    result: '成功' | '失败'
    extra?: string
  }
  createdAt: string
}

// ===================== Model & Prompt version domain =====================

/** Model version (3.4.4 model_version table) */
export interface ModelVersion {
  id: number
  modelName: string
  modelType: 'llm' | 'embedding'
  isDefault: boolean
  /** Quality regression-set eval metrics (200 labeled items; mandatory on model/Prompt change) */
  evalMetrics: { accuracy: number; falsePositive: number; adoptionRate: number | null }
  activatedAt: string
}

/** Prompt template (3.2.7: versioned management + variable injection) */
export interface PromptTemplate {
  id: number
  version: string
  scene: string
  content: string
  isActive: boolean
  updatedAt: string
}

// ===================== Intelligent Q&A domain =====================

/** RAG citation source kind */
export type QaCitationKind = 'law' | 'case' | 'template'

/** Knowledge item cited in a Q&A answer (hybrid-retrieval hit) */
export interface QaCitation {
  kind: QaCitationKind
  id: number
  title: string
  /** Hit snippet excerpt */
  snippet: string
  /** Hybrid-retrieval similarity (RRF-fused, normalized 0~1) */
  score: number
}

export interface QaMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  createdAt: string
  /** RAG citation list for an assistant message */
  citations?: QaCitation[]
  /** Agentic RAG decision chain (accumulated live from SSE agent_step events) */
  steps?: AgentStep[]
}

// ===================== Multi-agent collaboration domain (LangGraph) =====================

/** Agent implementation kind: tool-call loop / structured output / deterministic node */
export type AgentKind = 'llm' | 'structured' | 'deterministic'

/** Agent role registry (GET /agents) */
export interface AgentInfo {
  name: string
  role: string
  description: string
  /** Frontend i18n key for the description (backend Chinese is the fallback) */
  descKey?: string
  graph: string
  kind: AgentKind
  tools: string[]
}

/** Single-step agent_trace record (multi-agent collaboration timeline) */
export interface AgentTraceItem {
  id: number
  taskType: 'review' | 'qa'
  refId: number
  agentName: string
  role: string
  stepIdx: number
  action: string
  payload: Record<string, unknown>
  tokens: number
  latencyMs: number
  error: string | null
  createdAt: string
}

/** QA SSE agent_step event (Agentic RAG decision-chain step) */
export interface AgentStep {
  agent: string
  role: string
  summary: string
  detail?: Record<string, unknown>
}

// ===================== Login =====================

export interface LoginPayload {
  username: string
  password: string
}
