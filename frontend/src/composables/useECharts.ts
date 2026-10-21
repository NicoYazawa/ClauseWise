import { onBeforeUnmount, onMounted, shallowRef, type Ref } from 'vue'
import * as echarts from 'echarts'

/** On-demand ECharts composable: init + adaptive resize + auto-dispose */
export function useECharts(el: Ref<HTMLElement | null>) {
  const chart = shallowRef<echarts.ECharts | null>(null)

  function render(option: echarts.EChartsOption) {
    if (!el.value) return
    if (!chart.value) chart.value = echarts.init(el.value)
    chart.value.setOption(option, true)
  }

  function resize() {
    chart.value?.resize()
  }

  onMounted(() => window.addEventListener('resize', resize))
  onBeforeUnmount(() => {
    window.removeEventListener('resize', resize)
    chart.value?.dispose()
  })

  return { chart, render }
}
