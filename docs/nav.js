/* nav.js — Life After AI
   Injects the shared site nav at the top of <body>.
   Include in dashboard.html, archive.html.
   index.html has its own hand-coded nav (scroll-transparent). */

(function () {
  const pages = [
    { file: 'index.html',     label: '홈' },
    { file: 'dashboard.html', label: '리서치 맵' },
    { file: 'archive.html',   label: '아티클' },
    { file: 'admin.html',     label: '소스 관리' },
    { file: 'trinity.html',   label: 'Trinity Eye' },
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
          Life After AI
        </a>
        <div class="nav__links">${links}</div>
        <div class="nav__actions">
          <a href="./archive.html" class="btn btn-sm btn-primary">아티클 보기</a>
        </div>
      </div>
    </div>`;

  document.body.insertBefore(nav, document.body.firstChild);
})();
