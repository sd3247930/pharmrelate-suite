import { defineConfig, mergeConfig } from 'vitest/config';

import viteConfig from './vite.config';

/**
 * 测试配置单独成文件，而不是塞进 vite.config.ts。
 *
 * 原因：`test` 字段不属于 Vite 的 UserConfig 类型，写进 vite.config.ts 会让
 * `vue-tsc` 在生产构建时报错——生产构建不该依赖测试框架的类型。
 */
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      // 组件测试需要 DOM；路由与规则测试在 node 环境也能跑，统一用 happy-dom 更省心
      environment: 'happy-dom',
      include: ['src/**/*.spec.ts'],
    },
  }),
);
