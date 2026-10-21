/**
 * 设计令牌（Design tokens）
 *
 * 风格：Accent ladder（design-taste-frontend 抽取，seed 733247321）
 * 色阶由品牌青自建：满强度只出现在小标记（主按钮、数据线、激活图标），
 * 50–200 浅色调负责大面积（激活导航行、徽章底、进度条轨道）。
 *
 * 颜色统一以 CSS 变量（RGB 三元组）表达，支持 /alpha 透明度修饰符。
 * 禁止：紫色与靛蓝、渐变、发光、玻璃拟态、KPI 上的彩色图标方块。
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        // —— 地面与表面 ——
        ground: 'rgb(var(--c-ground) / <alpha-value>)',
        surface: 'rgb(var(--c-surface) / <alpha-value>)',
        raised: 'rgb(var(--c-raised) / <alpha-value>)',
        active: 'rgb(var(--c-active) / <alpha-value>)',
        // —— 分隔线三档 ——
        line: {
          DEFAULT: 'rgb(var(--c-border) / <alpha-value>)', // 卡片边
          rule: 'rgb(var(--c-rule) / <alpha-value>)', // 行分隔
          control: 'rgb(var(--c-control) / <alpha-value>)', // 控件边（比卡片边强一档）
        },
        // —— 文字三档（均满足 4.5:1） ——
        ink: {
          DEFAULT: 'rgb(var(--c-text) / <alpha-value>)',
          muted: 'rgb(var(--c-muted) / <alpha-value>)',
          faint: 'rgb(var(--c-faint) / <alpha-value>)',
        },
        // —— 品牌色阶（唯一强调色） ——
        accent: {
          DEFAULT: 'rgb(var(--c-accent) / <alpha-value>)', // 满强度：仅小标记
          hover: 'rgb(var(--c-accent-hover) / <alpha-value>)',
          soft: 'rgb(var(--c-accent-soft) / <alpha-value>)', // 浅色面：激活行 / 徽章底
          track: 'rgb(var(--c-accent-track) / <alpha-value>)', // 进度条轨道
          ink: 'rgb(var(--c-accent-ink) / <alpha-value>)', // 浅色面上的深色字
        },
        danger: {
          50: '#ffedea', 100: '#fecdd3', 200: '#fda4af', 300: '#fda4af', 400: '#e11d48', 500: '#c4242a', 600: '#c4242a',
          700: '#a01f24', 800: '#831c1e', 900: '#5f1418',
        },
        warn: {
          50: '#fffbeb', 100: '#fde68a', 200: '#fcd34d', 300: '#fcd34d', 400: '#f59e0b', 500: '#b45309', 600: '#b45309',
          700: '#92400e', 800: '#78350f', 900: '#78350f',
        },
        info: {
          50: '#f0f9ff', 100: '#bae6fd', 200: '#7dd3fc', 300: '#7dd3fc', 400: '#0ea5e9', 500: '#0369a1', 600: '#0369a1',
          700: '#075985', 800: '#0c4a6e', 900: '#0c4a6e',
        },
        success: {
          50: '#dcfce7', 100: '#a7f3d0', 200: '#6ee7b7', 300: '#6ee7b7', 400: '#34d399', 500: '#247b50', 600: '#247b50',
          700: '#14532d', 800: '#14532d', 900: '#052e16',
        },
      },
      fontFamily: {
        // DM Sans 为风格表抽取正文（拉丁），中文回退到系统黑体
        sans: ['DM Sans Variable', 'DM Sans', 'HarmonyOS Sans SC', 'PingFang SC', 'Microsoft YaHei', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
      fontSize: {
        // 屏幕字号只走这几档：页面标题 / 卡片标题 / KPI / 正文 / 元信息
        page: ['1.5rem', { lineHeight: '2rem', fontWeight: '600' }], // 24
        section: ['1.125rem', { lineHeight: '1.75rem', fontWeight: '600' }], // 18
        kpi: ['1.5rem', { lineHeight: '2rem' }], // 24，字重 400-500
        body: ['0.875rem', { lineHeight: '1.375rem' }], // 14
        meta: ['0.75rem', { lineHeight: '1.125rem' }], // 12
      },
      borderRadius: {
        card: 'var(--radius-card)', // 8
        ctl: 'var(--radius-control)', // 6
      },
      spacing: {
        ctl: 'var(--control-height)', // 32：同一上下文一个控件高度
        row: 'var(--row-height)', // 45
        sidebar: 'var(--sidebar-width)', // 230
        topbar: 'var(--topbar-height)', // 64
      },
      boxShadow: {
        // 静止元素不加阴影；只有真正浮起的层（菜单、弹窗、吐司）才有
        float: '0 8px 24px -8px rgb(15 23 42 / 0.16), 0 2px 6px -2px rgb(15 23 42 / 0.08)',
        card: '0 1px 2px 0 rgb(15 23 42 / 0.04)',
        'card-hover': '0 2px 8px 0 rgb(15 23 42 / 0.06)',
      },
      transitionTimingFunction: {
        swift: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
    },
  },
  plugins: [],
}
