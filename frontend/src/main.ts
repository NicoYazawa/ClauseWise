import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin } from '@tanstack/vue-query'
import { MotionPlugin } from 'motion-v'
import App from './App.vue'
import router from './router'
import toast from './plugins/toast'
import { queryClient } from './api/queryClient'
import i18n from './i18n'

// Self-hosted fonts (available offline; Chinese falls back to the system sans-serif)
import '@fontsource-variable/dm-sans'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(VueQueryPlugin, { queryClient })
app.use(router)
app.use(i18n)
app.use(toast)
// v-motion directive + <motion.div> component: overlay enter/exit, route transitions, list choreography
app.use(MotionPlugin)
app.mount('#app')
