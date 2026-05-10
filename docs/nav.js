/* nav.js — The AX Fieldbook
   Injects the shared site nav at the top of <body>.
   Include in dashboard.html, archive.html, admin.html.
   index.html has its own hand-coded nav (scroll-transparent). */

(function () {
  const pages = [
    { file: 'index.html',     label: '홈' },
    { file: 'dashboard.html', label: '대시보드' },
    { file: 'archive.html',   label: '아카이브' },
    { file: 'admin.html',     label: '소스 관리' },
  ];

  const current = location.pathname.split('/').pop() || 'index.html';

  const links = pages.map(({ file, label }) => {
    const active = current === file ? ' active' : '';
    return `<a href="./${file}" class="nav__link${active}">${label}</a>`;
  }).join('');

  const nav = document.createElement('nav');
  nav.className = 'nav';
  nav.setAttribute('aria-label', 'site navigation');
  nav.innerHTML = `
    <div class="container">
      <div class="nav__inner">
        <a href="./index.html" class="nav__logo">
          <div class="nav__logo-mark">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M7 1L13 4.5V9.5L7 13L1 9.5V4.5L7 1Z"/>
            </svg>
          </div>
          The AX Fieldbook
        </a>
        <div class="nav__links">${links}</div>
        <div class="nav__actions">
          <a href="./dashboard.html" class="btn btn-sm btn-primary">대시보드</a>
        </div>
      </div>
    </div>`;

  document.body.insertBefore(nav, document.body.firstChild);
})();
