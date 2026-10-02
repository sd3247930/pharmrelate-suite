# 签名修正记录：v1.4.6 重打包事件

> 日期：2026-10-03　范围：Android 采集端 APK 发布链路
> 结论：v1.4.6 已用**项目自有证书**重新打包并正式发布，可覆盖升级 v1.4.1，无需卸载。

## 一、事件经过

2026-10-02 23:53，HBuilderX 打出的 `PharmRelate Multi2.apk`（versionName 1.4.6 / versionCode 146）
在**发布前核验被拦下**：

| 项 | 值 |
| --- | --- |
| 包名 / 应用名 / 版本 | `com.pharmrelate.multi.capture` / 籽关通 / 1.4.6（146）—— 全部正确 |
| 六档启动图标 | 与仓库母版（`android/static/icons/app-icon-round-*`）逐字节一致 |
| **签名证书 SHA-256** | **`7b7fdc5c019a7e97447b17658a7b41983a07b1ef086ba212bfe51446c54ad52b`** |
| 已发布 v1.4.1 的签名 | `a2f926daebf2bb88d1d6537c208716790fbdd49f85cc820b6145a42907b59e48` |

签名主体为 `OU=Android, O=Android, C=CN` + 随机串 CN，且只有 v1/v2 签名方案、无 v3 密钥轮换 lineage
—— 是 **DCloud 云打包默认的「公共测试证书」**，不是工程的
`private\签名证书\pharmrelate-multi-capture.keystore`
（主体 `CN=PharmRelate Multi, OU=Mobile Capture, O=PharmRelate, C=CN`）。

**为什么危险**（两条都成立才拦住发布）：

1. 老用户装在手机上的旧版是自有证书签的，换成另一个证书后系统会拒绝覆盖安装
   （`INSTALL_FAILED_UPDATE_INCOMPATIBLE`），只能先卸载 —— 而批次数据只存在手机本机，卸载即丢。
2. 公共测试证书是公开可用的，任何人都能签出「同一签名」的包，等于给冒充升级开了口子。

另外，网页主按钮指向 `releases/latest`，一旦发出，所有点下载的人都会拿到装不上的包。

## 二、修正过程

1. 在 HBuilderX 云打包界面把证书从「公共测试证书」切换为「**自有证书**」：
   - keystore：`private\签名证书\pharmrelate-multi-capture.keystore`（JKS，别名 `pharmrelate`）
   - 口令：同目录 `证书口令.txt`（**只在本地保留，不入库**）
   - 版本保持 `versionName 1.4.6` / `versionCode 146` / 包名 `com.pharmrelate.multi.capture`
2. 2026-10-03 00:27 重新打包产出 `PharmRelate Multi3.apk`。
3. 发布前核验（`private\发布工具\check-release-apk.ps1`）：
   - 签名指纹 = `a2f926da…b59e48`，与登记值、仓库存档 keystore、已发布 v1.4.1 **三者一致** ✅
   - 包名 / 应用名 / versionName / versionCode / 六档图标全部通过 ✅
   - APK 内敏感数据抽查：无真实追溯码（`8206233` + 13 位）、无测试批次名；
     仅命中内置默认值（`workshop:一号车间`、`lineName:一号生产线`、`lineManager:操作员甲`、`license:1001123`）
     与界面文案「车间局域网」，属既有样例数据，非采集数据 ✅

## 三、v1.4.6 发布信息

| 项 | 值 |
| --- | --- |
| 仓库 | `sd3247930/pharmrelate-suite` |
| Release | `v1.4.6`（最新版） |
| 资产 | `PharmRelate-Multi-Capture.apk`（17,769,857 字节）+ `PharmRelate-Multi-Capture.apk.sha256` |
| APK 文件 SHA-256 | `4c938512321e124ca65dde5a6e37bf7c14a3f13efadea989c9e46c0a4d005ac0` |
| 签名证书 SHA-256 | `a2f926daebf2bb88d1d6537c208716790fbdd49f85cc820b6145a42907b59e48` |
| 固定直链 | `https://github.com/sd3247930/pharmrelate-suite/releases/latest/download/PharmRelate-Multi-Capture.apk` |
| 安装页 | `https://sd3247930.github.io/pharmrelate-suite/` |

## 四、发布后验证（2026-10-03）

| 项 | 结果 |
| --- | --- |
| 直链 | `302` → `…/download/v1.4.6/PharmRelate-Multi-Capture.apk` ✅ |
| 直链下载内容 | SHA-256 与发布包逐字节一致，且签名 = `a2f926da…` ✅ |
| `web/apk.json`（本地 + Pages） | `versionName 1.4.6` / `versionCode 146` / 正确 SHA256 与直链 ✅ |
| **真机覆盖安装** | 卸载旧包 → 装 v1.4.1（141，自有证书）→ `adb install -r` v1.4.6（146）→ **Success，无 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`**；`firstInstallTime` 保持不变（就地更新，数据目录未重建），升级后应用正常启动 ✅ |
| 回归 | `node tests/*.test.mjs` 746 项全过；`scripts/check-uniapp.ps1` 通过 ✅ |

## 五、版本说明

- **v1.4.2 ~ v1.4.5 为内部迭代版本，未对外发布**（GitHub 上只有 v1.4.0、v1.4.1、v1.4.6）。
  v1.4.4 把图库条码解码迁到 renderjs 视图层；v1.4.5 修候选列表删除；v1.4.6 统一候选行操作列几何。
- 后续升版仍走同一套流程：`scripts\publish-apk.ps1`（校验 → 固定资产名暂存 → Release → 回写 `web/apk.json` → 提交推送）。
  它的签名指纹门槛就是本次拦下错误包的机制，**不要绕过**。
- **APK 本身不入 Git**，二进制通过 Release 资产存档，仓库只存元数据（`web/apk.json`）与本记录。
