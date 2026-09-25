/**
 * 路由表。
 *
 * 采集流程严格对应 PRD 的界面 1～4：
 *   基础信息 → 包装结构 → 扫码采集 → 预览导出
 * 二期功能（多端协同 / 同步中心 / 冲突中心 / 审计日志 / 用户权限 / 系统设置）
 * 会在本文件补齐，导航栏已用"二期"标签占位。
 */

import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router';

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'dashboard',
    component: () => import('../views/DashboardView.vue'),
    meta: { title: '工作台', step: 0 },
  },
  {
    path: '/base-info',
    name: 'base-info',
    component: () => import('../views/BaseInfoView.vue'),
    meta: { title: '基础信息', step: 1 },
  },
  {
    path: '/package-structure',
    name: 'package-structure',
    component: () => import('../views/PackageStructureView.vue'),
    meta: { title: '包装结构', step: 2 },
  },
  {
    path: '/scanning',
    name: 'scanning',
    component: () => import('../views/ScanningView.vue'),
    meta: { title: '扫码采集', step: 3 },
  },
  {
    path: '/preview',
    name: 'preview',
    component: () => import('../views/PreviewView.vue'),
    meta: { title: '预览导出', step: 4 },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('../views/NotFoundView.vue'),
    meta: { title: '页面不存在' },
  },
];

export function createAppRouter(history = createWebHashHistory()) {
  return createRouter({ history, routes });
}

/**
 * 运行时路由实例。
 *
 * 刻意不在这里直接创建：`createWebHashHistory()` 会立即读取 `location`，
 * 而模块级调用会让路由表无法在 Node 环境（单元测试）里被导入。
 */
export function createHashRouter() {
  // Electron / Tauri 用 file:// 加载前端，因此必须使用 hash 模式
  return createAppRouter(createWebHashHistory());
}
