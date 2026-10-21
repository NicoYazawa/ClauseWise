/**
 * 生成 README 的中英双语功能截图。
 *
 * 用法（确保 docker compose 已启动）：
 *   cd frontend
 *   node scripts/capture-screenshots.mjs
 *
 * 产物：
 *   docs/images/zh/*.png   中文界面
 *   docs/images/en/*.png   英文界面
 *
 * 可选环境变量：
 *   CW_BASE_URL   默认 http://localhost:15173
 *   CW_USER       默认 zhangmy（演示账号：法务审查员）
 *   CW_PASS       默认 ClauseWise@2026Demo
 *   CW_CHROME     默认 C:\Program Files\Google\Chrome\Application\chrome.exe
 *   CW_LOCALES    默认 zh,en（只截一种时可设为 zh）
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const IMAGES = path.resolve(__dirname, '../../docs/images')
const BASE = process.env.CW_BASE_URL ?? 'http://localhost:15173'
const USER = process.env.CW_USER ?? 'zhangmy'
const PASS = process.env.CW_PASS ?? 'ClauseWise@2026Demo'
const CHROME = process.env.CW_CHROME ?? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const LOCALES = (process.env.CW_LOCALES ?? 'zh,en').split(',').map((s) => s.trim())

const browser = await chromium.launch({ executablePath: CHROME, headless: true })
let failed = 0

/** 单个语言下的完整截图流程 */
async function capture(locale) {
  const out = path.join(IMAGES, locale)
  fs.mkdirSync(out, { recursive: true })

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: locale === 'zh' ? 'zh-CN' : 'en-US',
    deviceScaleFactor: 1,
  })
  // 让应用启动时直接读到目标语言
  await context.addInitScript((value) => {
    try {
      localStorage.setItem('cw-locale', value)
    } catch {
      /* ignore */
    }
  }, locale === 'zh' ? 'zh-CN' : 'en-US')

  const page = await context.newPage()
  const shot = async (name, wait = 1600) => {
    await page.waitForTimeout(wait)
    await page.screenshot({ path: path.join(out, name) })
    console.log(`  ✓ ${locale}/${name}`)
  }

  try {
    // 1) 登录页
    await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' })
    await shot('01-login.png', 1800)

    // 登录
    await page.fill('#username', USER)
    await page.fill('#password', PASS)
    await page.click('button[type="submit"]')
    await page.waitForTimeout(4000)
    if (!page.url().includes('dashboard')) {
      await page.screenshot({ path: path.join(out, '_login-debug.png') })
      throw new Error(`登录后未进入工作台，当前 URL: ${page.url()}`)
    }
    await page.waitForTimeout(2000)

    // 2) 工作台
    await page.goto(BASE + '/dashboard', { waitUntil: 'domcontentloaded' })
    await shot('02-dashboard.png', 2600)

    // 3) 合同列表
    await page.goto(BASE + '/contracts', { waitUntil: 'domcontentloaded' })
    await shot('03-contracts.png', 2200)

    // 4) 合同详情：点第一行操作列的「查看」按钮（点整行不会跳转）
    await page.goto(BASE + '/contracts', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2000)
    const firstRow = page.locator('tbody tr').first()
    await firstRow.locator('button').first().click()
    await page.waitForTimeout(2800)
    if (!/\/contracts\/\d+/.test(page.url())) {
      await page.screenshot({ path: path.join(out, '_detail-debug.png') })
      throw new Error(`未进入合同详情，当前 URL: ${page.url()}`)
    }
    await shot('04-contract-detail.png', 2200)

    // 5) 审查报告：从任务列表进入第一条已完成的报告
    await page.goto(BASE + '/review', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2200)
    const reportEntry = page.locator('tbody tr').first().locator('a, button').last()
    await reportEntry.click()
    await page.waitForTimeout(3200)
    await page.screenshot({ path: path.join(out, '05-review-report.png') })
    console.log(`  ✓ ${locale}/05-review-report.png`)

    // 6) 审批中心
    await page.goto(BASE + '/workflow', { waitUntil: 'domcontentloaded' })
    await shot('06-workflow.png', 2200)

    // 7) 法律法规库
    await page.goto(BASE + '/knowledge/laws', { waitUntil: 'domcontentloaded' })
    await shot('07-laws.png', 2200)

    // 8) 企业模板库
    await page.goto(BASE + '/knowledge/templates', { waitUntil: 'domcontentloaded' })
    await shot('08-templates.png', 2000)

    // 9) 智能问答：提一个真实问题，等流式回答结束
    await page.goto(BASE + '/knowledge/qa', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(1500)
    try {
      const question = locale === 'zh' ? '违约金约定多少可能被司法调减？' : 'When may a liquidated damages clause be reduced by a court?'
      await page.locator('textarea').fill(question)
      await page.locator('textarea').press('Enter')
      await page.waitForTimeout(16000)
    } catch {
      /* 发送失败时保留欢迎态截图 */
    }
    await page.screenshot({ path: path.join(out, '09-qa.png') })
    console.log(`  ✓ ${locale}/09-qa.png`)

    // 10) Agent 协作总览
    await page.goto(BASE + '/system/agents', { waitUntil: 'domcontentloaded' })
    await shot('10-agents.png', 2600)
  } finally {
    await context.close()
  }
}

try {
  // 兼容旧版截图目录：清理根级 png
  if (fs.existsSync(IMAGES)) {
    for (const file of fs.readdirSync(IMAGES)) {
      if (file.endsWith('.png')) fs.unlinkSync(path.join(IMAGES, file))
    }
  }

  for (const locale of LOCALES) {
    console.log(`\n[${locale}]`)
    try {
      await capture(locale)
    } catch (error) {
      failed += 1
      console.error(`✗ ${locale}: ${error instanceof Error ? error.message : String(error)}`)
    }
  }
} finally {
  await browser.close()
}

console.log(failed === 0 ? '\n全部截图完成' : `\n完成，${failed} 个语言失败`)
process.exit(failed === 0 ? 0 : 1)
