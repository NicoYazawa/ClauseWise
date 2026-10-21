<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { askQuestionStream } from '@/api/qa'
import type { QaMessage, QaCitation } from '@/types'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Icon from '@/components/ui/Icon.vue'

const { t } = useI18n()

/** Welcome-page quick questions (static suggested copy; clicking routes to the real RAG Q&A API) */
const quickQuestions = computed(() => [
  t('knowledge.qa.quick1'),
  t('knowledge.qa.quick2'),
  t('knowledge.qa.quick3'),
  t('knowledge.qa.quick4'),
  t('knowledge.qa.quick5'),
  t('knowledge.qa.quick6'),
])

const messages = ref<QaMessage[]>([])
const input = ref('')
const asking = ref(false)
const listEl = ref<HTMLElement | null>(null)
const expanded = ref<Set<number>>(new Set())
const stepExpanded = ref<Set<number>>(new Set())

let msgSeq = 1
let lastScrollAt = 0

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function nowIso(): string {
  return new Date().toISOString().slice(0, 19)
}

async function scrollToBottom() {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}

/** Scroll throttling during streaming (scrolling on every delta causes jank) */
function maybeScroll() {
  const now = Date.now()
  if (now - lastScrollAt > 200) {
    lastScrollAt = now
    scrollToBottom()
  }
}

async function send(text?: string) {
  const q = (text ?? input.value).trim()
  if (!q || asking.value) return
  input.value = ''
  messages.value.push({ id: msgSeq++, role: 'user', content: q, createdAt: nowIso() })

  messages.value.push({ id: msgSeq++, role: 'assistant', content: '', createdAt: nowIso(), citations: [], steps: [] })
  // Key: we must grab the deep reactive proxy after push; mutating the raw object passed into push does not trigger view updates,
  // which would make all deltas burst out at once at the end
  const reply = messages.value[messages.value.length - 1]
  asking.value = true
  scrollToBottom()

  // Smooth-render queue: upstream chunk granularity is uneven (flash models often flush within a very short time),
  // a fixed-cadence consumer renders char-by-char; the more backlog, the faster it drains, keeping streaming smooth without a long tail
  const queue: string[] = []
  let streamEnded = false
  let rendered = ''

  const pump = async () => {
    while (!streamEnded || queue.length > 0) {
      if (queue.length === 0) {
        await sleep(20)
        continue
      }
      const batch = Math.min(queue.length, Math.max(1, Math.ceil(queue.length / 8)))
      for (let i = 0; i < batch; i++) rendered += queue.shift()
      reply.content = rendered
      maybeScroll()
      await sleep(20)
    }
    reply.content = rendered
  }
  const pumping = pump()

  try {
    // Real SSE streaming: the Agent decision chain and citations are pushed first, then the answer is generated chunk by chunk (Agentic RAG pipeline)
    await askQuestionStream(q, {
      onAgentStep: (step) => {
        reply.steps?.push(step)
        maybeScroll()
      },
      onCitations: (citations) => {
        reply.citations = citations // CRAG error-correction recheck uses overwrite-style updates
        scrollToBottom()
      },
      onDelta: (piece) => {
        queue.push(piece)
      },
      onReset: () => {
        // SelfRAG reflection failed -> regenerate: clear the current render and backlog queue, then receive subsequent deltas
        rendered = ''
        queue.length = 0
        reply.content = ''
      },
    })
  } catch (e) {
    const tip = t('knowledge.qa.errorTip', { message: (e as Error).message })
    queue.push(rendered ? `\n\n${tip}` : tip)
  } finally {
    streamEnded = true
    await pumping // Wait for the queue to drain before ending the loading state, to avoid abruptly truncating the tail text
    asking.value = false
    scrollToBottom()
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function toggleCitation(id: number) {
  const s = new Set(expanded.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  expanded.value = s
}

function toggleSteps(id: number) {
  const s = new Set(stepExpanded.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  stepExpanded.value = s
}

const kindBadge = computed<Record<QaCitation['kind'], { label: string; tone: 'primary' | 'info' | 'warn' }>>(() => ({
  law: { label: t('knowledge.qa.kindLaw'), tone: 'primary' },
  case: { label: t('knowledge.qa.kindCase'), tone: 'info' },
  template: { label: t('knowledge.qa.kindTemplate'), tone: 'warn' },
}))
</script>

<template>
  <div>
    <PageHeader
      :title="t('knowledge.qa.title')"
      :description="t('knowledge.qa.description')"
    >
      <template #actions>
        <span class="flex items-center gap-1.5 text-xs text-ink-faint">
          <Icon name="cpu" :size="13" />
          {{ t('knowledge.qa.modelNote') }}
        </span>
      </template>
    </PageHeader>

    <div class="card flex flex-col overflow-hidden">
      <!-- Message area -->
      <div ref="listEl" class="flex-1 overflow-y-auto px-5 py-6 space-y-5 min-h-[420px] max-h-[calc(100vh-360px)]">
        <!-- Welcome state -->
        <div v-if="messages.length === 0" class="max-w-2xl mx-auto text-center pt-8 pb-4">
          <span class="inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-soft text-accent">
            <Icon name="sparkles" :size="26" />
          </span>
          <h2 class="mt-4 text-lg font-bold text-ink">{{ t('knowledge.qa.welcomeTitle') }}</h2>
          <p class="mt-2 text-sm text-ink-muted leading-relaxed">
            {{ t('knowledge.qa.welcomeDesc1') }}
            <br class="hidden md:block" />
            {{ t('knowledge.qa.welcomeDesc2') }}
          </p>
          <div class="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-w-xl mx-auto text-left">
            <button
              v-for="q in quickQuestions"
              :key="q"
              class="flex items-center gap-2 rounded-lg border border-line px-3.5 py-2.5 text-sm text-ink-muted hover:border-accent hover:bg-accent-soft/40 hover:text-accent-ink transition-colors"
              @click="send(q)"
            >
              <Icon name="book-open" :size="14" class="text-accent shrink-0" />
              <span class="truncate">{{ q }}</span>
            </button>
          </div>
        </div>

        <!-- Conversation messages -->
        <template v-for="m in messages" :key="m.id">
          <!-- User message -->
          <div v-if="m.role === 'user'" class="flex justify-end">
            <div class="max-w-[78%] rounded-2xl rounded-br-sm bg-accent px-4 py-2.5 text-sm text-white leading-relaxed whitespace-pre-wrap">
              {{ m.content }}
            </div>
          </div>

          <!-- Assistant message -->
          <div v-else class="flex items-start gap-3">
            <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
              <Icon name="sparkles" :size="15" />
            </span>
            <div class="max-w-[85%] min-w-0">
              <!-- Agent decision chain (Agentic RAG: route -> plan -> retrieve -> evaluate -> correct -> reflect) -->
              <div v-if="m.steps && m.steps.length > 0" class="mb-1.5">
                <button
                  class="w-full flex items-center gap-1.5 rounded-lg border border-dashed border-line bg-raised/70 px-3 py-1.5 text-left hover:border-accent-track transition-colors"
                  @click="toggleSteps(m.id)"
                >
                  <Icon name="cpu" :size="12" class="text-accent shrink-0" />
                  <span class="text-[11px] font-medium text-ink-muted">{{ t('knowledge.qa.stepsLabel', { n: m.steps.length }) }}</span>
                  <span class="text-[11px] text-ink-faint truncate">{{ m.steps.map((s) => s.role).join(' → ') }}</span>
                  <Icon :name="stepExpanded.has(m.id) ? 'chevron-down' : 'chevron-right'" :size="12" class="ml-auto text-line-control shrink-0" />
                </button>
                <ol v-if="stepExpanded.has(m.id)" class="mt-1.5 space-y-1">
                  <li
                    v-for="(s, si) in m.steps"
                    :key="si"
                    class="flex items-start gap-2 rounded-md bg-white border border-line-rule px-2.5 py-1.5"
                  >
                    <span class="mt-0.5 inline-flex shrink-0 rounded bg-accent-soft px-1.5 py-0.5 text-[10px] font-medium text-accent">{{ s.role }}</span>
                    <span class="text-[11px] text-ink-muted leading-relaxed">{{ s.summary }}</span>
                  </li>
                </ol>
              </div>
              <div class="rounded-2xl rounded-tl-sm border border-line bg-white px-4 py-3 text-sm text-ink leading-relaxed whitespace-pre-wrap">
                <template v-if="m.content">{{ m.content }}</template>
                <span v-else-if="asking" class="flex items-center gap-2 text-ink-faint">
                  <Icon name="refresh" :size="14" class="animate-spin" />
                  {{ t('knowledge.qa.retrieving') }}
                </span>
              </div>

              <!-- RAG citation sources (citations pushed first, traceable during generation) -->
              <div v-if="m.citations && m.citations.length > 0" class="mt-2.5 space-y-1.5">
                <p class="flex items-center gap-1.5 text-xs font-medium text-ink-faint">
                  <Icon name="database" :size="12" />
                  {{ t('knowledge.qa.citationsLabel', { n: m.citations.length }) }}
                </p>
                <button
                  v-for="c in m.citations"
                  :key="`${c.kind}-${c.id}`"
                  class="w-full text-left rounded-lg border border-line bg-raised/60 px-3 py-2 hover:border-accent-track transition-colors"
                  @click="toggleCitation(c.id)"
                >
                  <span class="flex items-center gap-2">
                    <BaseBadge :tone="kindBadge[c.kind].tone">{{ kindBadge[c.kind].label }}</BaseBadge>
                    <span class="text-xs font-medium text-ink truncate">{{ c.title }}</span>
                    <span class="ml-auto text-[10px] font-mono text-ink-faint shrink-0">{{ t('knowledge.qa.similarity', { score: c.score.toFixed(2) }) }}</span>
                    <Icon :name="expanded.has(c.id) ? 'chevron-down' : 'chevron-right'" :size="13" class="text-line-control shrink-0" />
                  </span>
                  <p v-if="expanded.has(c.id)" class="mt-2 pb-0.5 text-xs text-ink-muted leading-relaxed">
                    {{ c.snippet }}
                    <router-link to="/knowledge/laws" class="ml-1 text-accent hover:underline">{{ t('knowledge.qa.viewKnowledge') }}</router-link>
                  </p>
                </button>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- Input area -->
      <div class="border-t border-line-rule p-4">
        <div class="flex items-end gap-3">
          <textarea
            v-model="input"
            rows="1"
            class="input resize-none flex-1 max-h-28"
            :placeholder="t('knowledge.qa.inputPlaceholder')"
            :disabled="asking"
            @keydown="onKeydown"
          />
          <BaseButton icon="send" :loading="asking" :disabled="!input.trim()" @click="send()">{{ t('knowledge.qa.send') }}</BaseButton>
        </div>
        <p class="mt-2 flex items-center gap-1 text-[11px] text-ink-faint">
          <Icon name="info" :size="11" />
          {{ t('knowledge.qa.disclaimer') }}
        </p>
      </div>
    </div>
  </div>
</template>
