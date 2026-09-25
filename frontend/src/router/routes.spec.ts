/**
 * 路由表测试：验证 4 个采集流程路由确实可达且能解析出组件。
 *
 * 之所以用测试而不是截图核对：路由切换是纯逻辑，测试可重复、可在 CI 跑，
 * 而且能精确指出是哪一条路径断掉。
 */

import { createMemoryHistory } from 'vue-router';
import { describe, expect, it } from 'vitest';

import { createAppRouter, routes } from './index';

const FLOW_ROUTES = [
  { path: '/', name: 'dashboard', title: '工作台' },
  { path: '/base-info', name: 'base-info', title: '基础信息' },
  { path: '/package-structure', name: 'package-structure', title: '包装结构' },
  { path: '/scanning', name: 'scanning', title: '扫码采集' },
  { path: '/preview', name: 'preview', title: '预览导出' },
];

describe('采集流程路由', () => {
  it('五个页面按顺序注册了正确的 name 与标题', () => {
    const flow = routes.filter((route) => route.meta?.step !== undefined);
    expect(flow.map((route) => route.name)).toEqual(FLOW_ROUTES.map((route) => route.name));
    expect(flow.map((route) => route.meta?.title)).toEqual(FLOW_ROUTES.map((route) => route.title));
    expect(flow.map((route) => route.meta?.step)).toEqual([0, 1, 2, 3, 4]);
  });

  it.each(FLOW_ROUTES)('$path 可解析到 $name 并且组件能加载', async ({ path, name }) => {
    const router = createAppRouter(createMemoryHistory());
    await router.push(path);
    await router.isReady();

    expect(router.currentRoute.value.name).toBe(name);
    const component = router.currentRoute.value.matched[0]?.components?.default;
    // 懒加载组件此时应当已经被解析成真实组件对象，而不是函数
    expect(component).toBeTruthy();
    expect(typeof component).not.toBe('function');
  });

  it('未知路径落到 404 页面而不是白屏', async () => {
    const router = createAppRouter(createMemoryHistory());
    await router.push('/不存在的路径');
    await router.isReady();
    expect(router.currentRoute.value.name).toBe('not-found');
  });
});
