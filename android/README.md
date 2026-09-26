# 籽关通 Android 采集端（uni-app）

> 路线：HBuilderX + uni-app（**不是 Capacitor**）
> 状态：工程骨架，可试跑
> 位置：`<ANDROID_PROJECT_DIR>`
> （主仓库内 `android\` 是指向该目录的 junction，两处始终是同一份文件）

---

## 〇、工程放在哪

2026-09-26 起，本工程的实际文件放在 HBuilderX 项目目录：

```
<ANDROID_PROJECT_DIR>
```

主仓库里的 `android\` 是一个 **目录 junction**，指向上面的目录。这样：

- HBuilderX 打开的是普通本地目录，没有链接兼容问题；
- 主仓库的 git 仍然跟踪同一批文件，`docs/`、`scripts/check-uniapp.ps1` 的引用不用改；
- 在 HBuilderX 里编辑 = 编辑仓库内的文件，提交历史不断。

**注意**：junction 不入 git。新克隆仓库的机器上 `android\` 会缺失，
需要把该目录复制回去，或在新机器上重新建 junction —— 详见
`docs/52-Android工程位置与迁移记录.md`。

---

## 一、这是什么

车间操作员手里的移动扫码端。按此前确认的范围，**只做三件事**：

1. 扫码（箱号 / 罐号 / 粒子码）
2. 显示当前状态与进度
3. 把识别结果提交给 Windows 主控机

**识别、状态机、拦截规则、去重、审计全部在 Windows 服务端**，
移动端不做任何本地业务判定 —— 它只是"另一个提交识别结果的来源"。

---

## 二、为什么不是 Capacitor

此前规划假设用 Capacitor 包装现有 Vue web 前端，实际工具链是 HBuilderX/uni-app。
两者约束不同：

| 能力 | Capacitor | uni-app（本项目） |
| --- | --- | --- |
| 界面 | 复用 web 前端 | App 端无 DOM，须用 `<view>/<text>` |
| 相机扫码 | 社区插件 | `uni.scanCode()`（原生，更稳） |
| WebSocket | WebView 发起 | `uni.connectSocket()`，**原生网络栈** |
| 声音 | WebAudio | `uni.vibrateLong()`（当前用震动提示） |
| 存储 | localStorage | `uni.setStorageSync` |

所以 Android 端是**重写的精简版页面**，不是把桌面端 UI 搬过来。

---

## 三、目录

```
android/
├── manifest.json          应用配置、Android 权限
├── pages.json             三页路由 + 底部 tabBar
├── App.vue / main.js      入口（Vue 2/3 双兼容写法）
├── pages/
│   ├── scan/scan.vue      扫码主流程
│   ├── status/status.vue  整体核对 + 提前结束
│   └── settings/settings.vue  服务地址、配对、选批次
├── services/
│   ├── api.js             /api/scan/* 会话 API 客户端
│   ├── ws.js              uni.connectSocket 封装（docs/43 信封）
│   └── store.js           本地配置与设备指纹
└── unpackage/             构建产物（已 gitignore）
```

---

## 四、第一次跑起来

### 4.1 先让 Windows 端能被手机访问

**这是最容易卡住的一步。** 默认启动只监听 `127.0.0.1`，手机连不上。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\serve-lan.ps1
```

脚本会以 `--host 0.0.0.0` 启动，并打印本机局域网 IP。**手机端要填的就是这个地址。**

同时确认 Windows 防火墙允许 17800 端口入站（首次运行会弹提示，选"允许"）。

### 4.2 HBuilderX 打开工程

1. HBuilderX → 文件 → 打开目录 → 选择本目录
   （`<ANDROID_PROJECT_DIR>`）
2. 登录 DCloud 账号（运行到 App 基座必须登录）
3. appid 已随工程带入：`__UNI__DA0B962`（本机 HBuilderX 获取的，
   不再是占位值 `__UNI__PHARMRELATE`）。若需换绑其他账号，
   manifest.json 可视化界面 → 重新获取 appid。

### 4.3 真机运行

按截图所示的路径：

```
运行(R) → 运行到手机或模拟器(N) → 运行到Android App基座(D)
```

前提：手机开启 USB 调试并用数据线连上电脑，HBuilderX 能识别到设备。

### 4.4 在手机上配置

1. 打开 App → 底部「设置」
2. **服务地址**填 `http://<上一步打印的局域网IP>:17800`
3. 点「测试连接」，看到服务版本即为通
4. 点「读取批次列表」，选一个「采集中」的批次
5. 回到「扫码」页，按提示扫箱号 → 罐号 → 粒子

---

## 五、扫码流程与桌面端一致

状态全部由服务端返回，界面上看到的提示就是服务端的原话：

| 服务端状态 | 界面显示 | 操作 |
| --- | --- | --- |
| `box_scanning` | 请扫描箱号 | 扫 1 个码，确认 |
| `can_scanning` | 请扫描罐 N 号 | 扫 1 个码，确认 |
| `particle_scanning` | 请扫描罐 N 的粒子 | 逐个扫，满了自动进核对 |
| `can_review` | 罐 N 已扫满 | 确认无误 / 还没好 |
| `next_can_prompt` | 是否继续下一罐 | 继续 / 提前结束 |
| `overall_review` | 所有罐已完成 | 前往整体核对 |

拦截（多码、错层、重复、溢出）由服务端判定，手机只负责展示恢复路径。
需要报警时用**震动**（`uni.vibrateLong`）——App 端没有 WebAudio。

---

## 六、还没做的

| 项 | 说明 |
| --- | --- |
| 粒子批量多码 | 当前是「一次扫一个」。一张纸 6 枚的批量识别需要「拍照上传 → 服务端识别」，复用一期抗反光管线，属二期二批 |
| mDNS 自动发现 | 现在靠手填地址。mDNS 需要真机验证组播权限 |
| WSS | 现在走 `ws://`（选项 B）。A-07 待真机预研后判定 |
| 离线补发 | 断网时无法扫码。离线队列是二期内核的内容 |
| 账号登录 | 一期单机无账号体系 |

---

## 七、验收标准（对应执行方案第 1 项）

- [ ] HBuilderX 打开工程无报错
- [ ] 三页路由可切换
- [ ] `uni.scanCode()` 可调用
- [ ] `/api/scan/*` 客户端可调通
- [ ] `uni.connectSocket` 可连接 PC 端 ws 服务
- [ ] `manifest.json` 权限配置完整
- [ ] 不修改一期代码
- [ ] 不新增数据库表结构
