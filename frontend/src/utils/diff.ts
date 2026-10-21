/** Per-character diff segments (3.2.5: original/suggestion side-by-side char-level diff highlighting) */
export interface DiffSeg {
  type: 'same' | 'del' | 'add'
  text: string
}

/** Above this length, fall back to whole-segment display to avoid LCS compute & render cost */
const MAX_DIFF_LEN = 1500

function pushSeg(ops: DiffSeg[], type: DiffSeg['type'], text: string): void {
  const last = ops[ops.length - 1]
  if (last && last.type === type) last.text += text
  else ops.push({ type, text })
}

/** Char-level LCS diff: returns left (original w/ deletions) & right (suggestion w/ additions) segment lists */
export function diffText(oldText: string, newText: string): { left: DiffSeg[]; right: DiffSeg[] } {
  if (oldText === newText) {
    const seg: DiffSeg[] = [{ type: 'same', text: oldText }]
    return { left: seg, right: [{ type: 'same', text: newText }] }
  }
  if (oldText.length > MAX_DIFF_LEN || newText.length > MAX_DIFF_LEN || !oldText || !newText) {
    return { left: [{ type: 'same', text: oldText }], right: [{ type: 'same', text: newText }] }
  }
  const a = Array.from(oldText)
  const b = Array.from(newText)
  const n = a.length
  const m = b.length
  // dp[i][j] = LCS length of a[i:] and b[j:]
  const dp: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const ops: DiffSeg[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      pushSeg(ops, 'same', a[i])
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      pushSeg(ops, 'del', a[i])
      i++
    } else {
      pushSeg(ops, 'add', b[j])
      j++
    }
  }
  while (i < n) pushSeg(ops, 'del', a[i++])
  while (j < m) pushSeg(ops, 'add', b[j++])
  return {
    left: ops.filter((o) => o.type !== 'add'),
    right: ops.filter((o) => o.type !== 'del'),
  }
}

/** Char overlap ratio (rough similarity): below threshold fall back to whole-segment display to avoid noisy all-red/all-green diffs */
export function similarity(oldText: string, newText: string): number {
  if (!oldText && !newText) return 1
  const setB = new Set(Array.from(newText))
  let common = 0
  for (const ch of oldText) if (setB.has(ch)) common++
  return common / Math.max(oldText.length, newText.length, 1)
}
