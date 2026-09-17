'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('pet', {
  /** 把"命中网格"交给主进程：哪些区域会挡住桌面点击 */
  updateCoverage: (c) => ipcRenderer.send('coverage:update', c),

  /** 主进程判定光标是否落在宠物身上（决定穿透与面板浮出） */
  onHoverChanged: (fn) => ipcRenderer.on('hover:changed', (_e, on) => fn(on)),

  /** 通知主进程当前场景，用于托盘菜单打勾 */
  notifyScene: (key) => ipcRenderer.send('scene:changed', key),

  /** 托盘菜单 -> 渲染进程 */
  onSceneSet: (fn) => ipcRenderer.on('scene:set', (_e, key) => fn(key)),
  onOffer: (fn) => ipcRenderer.on('action:offer', () => fn()),
  onReset: (fn) => ipcRenderer.on('action:reset', () => fn()),
  onZoomChanged: (fn) => ipcRenderer.on('zoom:changed', (_e, z) => fn(z)),

  /** 窗口控制 */
  hide: () => ipcRenderer.send('app:hide'),
  quit: () => ipcRenderer.send('app:quit'),
  resetPosition: () => ipcRenderer.send('win:resetPosition'),

  /** 宠物大小 */
  getZoom: () => ipcRenderer.invoke('zoom:get'),
  setZoom: (z) => ipcRenderer.invoke('zoom:set', z),
  stepZoom: (dir) => ipcRenderer.invoke('zoom:step', dir),
});
