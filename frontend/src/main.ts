import { createPinia } from 'pinia';
import { createApp } from 'vue';

// 样式入口顺序：令牌必须最先加载，基础样式依赖令牌变量
import './styles/tokens.css';
import './styles/base.css';
import App from './App.vue';
import { initApiBase } from './api/client';
import { createHashRouter } from './router';

// 先解析后端地址，再挂载，避免首屏的 /api/health 打到错误地址
await initApiBase();

createApp(App).use(createPinia()).use(createHashRouter()).mount('#app');
