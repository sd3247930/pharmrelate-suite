/* ============================================================
   籽关通（PharmRelate Multi）手机端分发站 · 交互
   设计约束：
   1) 主下载按钮的 href / download 在 HTML 里写死，本文件只做「再确认一遍」，
      任何 JS 或 apk.json 失败都不能让下载变成不可用。
   2) 「📲 安装」入口在独立窗口（PWA / APK 内）与 file:// 下必须消失。
   3) 面板是底部抽屉：aria-expanded 跟随状态，ESC / 点遮罩 / 关闭按钮都能收，
      关闭后焦点回到入口按钮。
   ============================================================ */
(function () {
  'use strict';

  var DOWNLOAD_URL =
    'https://github.com/sd3247930/PharmRelate-Multi/releases/latest/download/PharmRelate-Multi-Capture.apk';
  var APK_NAME = 'PharmRelate-Multi-Capture.apk';

  var root = document.documentElement;
  var installBtn = document.getElementById('installBtn');
  var panel = document.getElementById('installPanel');
  var backdrop = document.getElementById('installBackdrop');
  var closeBtn = document.getElementById('installClose');
  var downloadLink = document.getElementById('apkDownload');
  var rawUrlInput = document.getElementById('apkRawUrl');
  var copyBtn = document.getElementById('apkCopyBtn');
  var copyNote = document.getElementById('apkCopyNote');
  var pending = document.getElementById('apkPending');

  /* ---------- 1. 主按钮：固定资产名直链（不依赖 JS 也成立，这里只兜底） ---------- */
  if (downloadLink) {
    downloadLink.setAttribute('href', DOWNLOAD_URL);
    downloadLink.setAttribute('download', APK_NAME);
  }
  if (rawUrlInput) { rawUrlInput.value = DOWNLOAD_URL; }

  /* ---------- 2. 独立窗口 / file:// 下隐藏安装入口 ---------- */
  var standalone = false;
  try {
    standalone =
      (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
      (window.matchMedia && window.matchMedia('(display-mode: fullscreen)').matches) ||
      window.navigator.standalone === true ||
      typeof window.plus !== 'undefined' ||
      /Html5Plus|HBuilder|uni-app|StreamApp/i.test(window.navigator.userAgent || '');
  } catch (err) {
    standalone = false;
  }
  var openedFromFile = window.location.protocol === 'file:';
  if (standalone || openedFromFile) {
    root.classList.add('no-install-entry');
  }

  /* ---------- 3. 底部面板开关 ---------- */
  var lastFocus = null;
  var isOpen = false;

  function openPanel() {
    if (isOpen || !panel || root.classList.contains('no-install-entry')) { return; }
    isOpen = true;
    lastFocus = document.activeElement;
    panel.hidden = false;
    if (backdrop) { backdrop.hidden = false; }
    // 强制一次重排，让 transition 生效（否则 hidden -> 显示 与 translate 同帧，动画会被吃掉）
    void panel.offsetHeight;
    panel.classList.add('show');
    if (backdrop) { backdrop.classList.add('show'); }
    document.body.classList.add('sheet-open');
    if (installBtn) { installBtn.setAttribute('aria-expanded', 'true'); }
    if (closeBtn) { closeBtn.focus({ preventScroll: true }); }
  }

  function closePanel() {
    if (!isOpen || !panel) { return; }
    isOpen = false;
    panel.classList.remove('show');
    if (backdrop) { backdrop.classList.remove('show'); }
    document.body.classList.remove('sheet-open');
    if (installBtn) { installBtn.setAttribute('aria-expanded', 'false'); }
    window.setTimeout(function () {
      if (isOpen) { return; }
      panel.hidden = true;
      if (backdrop) { backdrop.hidden = true; }
    }, 260);
    if (lastFocus && typeof lastFocus.focus === 'function') {
      lastFocus.focus({ preventScroll: true });
    }
  }

  if (installBtn) {
    installBtn.addEventListener('click', function () {
      if (isOpen) { closePanel(); } else { openPanel(); }
    });
  }
  if (closeBtn) { closeBtn.addEventListener('click', closePanel); }
  if (backdrop) { backdrop.addEventListener('click', closePanel); }
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' || event.key === 'Esc') { closePanel(); }
  });

  /* ---------- 4. 深链：?install=1 / #install 自动弹出面板 ---------- */
  var query = window.location.search || '';
  var wantsPanel = /(^|[?&])install=(1|true|yes)(&|$)/i.test(query) ||
                   window.location.hash === '#install';
  if (wantsPanel) {
    window.setTimeout(openPanel, 120);
  }

  /* ---------- 5. 版本信息：读 apk.json，失败就保留页面上的静态文案 ---------- */
  function formatSize(bytes) {
    if (typeof bytes !== 'number' || !isFinite(bytes) || bytes <= 0) { return ''; }
    var mb = bytes / 1048576;
    if (mb >= 1) { return mb.toFixed(1) + ' MB'; }
    return Math.round(bytes / 1024) + ' KB';
  }

  function setText(id, text) {
    var el = document.getElementById(id);
    if (el && text) { el.textContent = text; }
  }

  fetch('apk.json', { cache: 'no-store' })
    .then(function (res) {
      if (!res.ok) { throw new Error('apk.json ' + res.status); }
      return res.json();
    })
    .then(function (meta) {
      var version = meta.versionName
        ? meta.versionName + (meta.tag && meta.tag !== ('v' + meta.versionName) ? '（' + meta.tag + '）' : '')
        : '';
      var size = formatSize(meta.sizeBytes);
      var date = meta.releasedAt || '';

      setText('apkVersion', version);
      setText('apkSize', size);
      setText('apkDate', date);
      setText('apkSha', meta.sha256 || '');
      setText('apkPackage', meta.packageName || '');
      setText('footVersion', [version, date, size].filter(Boolean).join(' · '));

      if (pending) {
        if (meta.released === false) {
          pending.hidden = false;
          pending.textContent = '安装包尚未发布：等首个 Release 上传后，这里会显示版本、大小与校验值。';
        } else {
          pending.hidden = true;
        }
      }
    })
    .catch(function () {
      // 静态文案即兜底：不写任何东西，页面照旧可下载
      setText('footVersion', '见下方安装面板');
    });

  /* ---------- 6. 复制直链（微信等浏览器里点不动时的兜底） ---------- */
  if (copyBtn && rawUrlInput) {
    copyBtn.addEventListener('click', function () {
      var text = rawUrlInput.value;
      var done = function () {
        if (copyNote) { copyNote.textContent = '已复制 ✓'; }
        window.setTimeout(function () { if (copyNote) { copyNote.textContent = ''; } }, 2400);
      };
      var failed = function () {
        rawUrlInput.select();
        if (copyNote) { copyNote.textContent = '请长按选中后复制'; }
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, failed);
      } else {
        try {
          rawUrlInput.select();
          document.execCommand('copy') ? done() : failed();
        } catch (err) {
          failed();
        }
      }
    });
  }
})();
