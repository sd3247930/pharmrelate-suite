/**
 * 预加载脚本：把后端地址以只读方式暴露给渲染进程。
 *
 * 只暴露这一个取值函数，不开放 Node 能力，渲染进程始终运行在
 * contextIsolation + 禁用 nodeIntegration 的环境里。
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('pharmrelate', {
  apiBaseUrl: () => ipcRenderer.invoke('pharmrelate:api-base-url'),
});
