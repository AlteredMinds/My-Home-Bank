(function () {
  const txList = document.getElementById('tx-list');
  if (!txList) return;

  const txItems = Array.from(txList.querySelectorAll('.tx-item'));
  const pagination = document.getElementById('tx-pagination');
  const perPage = 10;
  let currentPage = 1;

  function renderPage(page) {
    currentPage = page;
    const start = (page - 1) * perPage;
    const end = start + perPage;

    txItems.forEach((item, i) => {
      item.style.display = i >= start && i < end ? 'flex' : 'none';
    });

    renderPagination();
  }

  function renderPagination() {
    pagination.innerHTML = '';
    const totalPages = Math.ceil(txItems.length / perPage);
    if (totalPages <= 1) return;

    for (let i = 1; i <= totalPages; i++) {
      const btn = document.createElement('button');
      btn.textContent = i;
      btn.className = 'tx-page-btn';
      btn.addEventListener('click', () => renderPage(i));
      pagination.appendChild(btn);
    }
  }

  document.querySelectorAll('.tx-ts').forEach(el => {
    const utc = el.dataset.utc;
    const dt = new Date(utc);
    el.textContent = dt.toLocaleString(undefined, {
      month: 'short',
      day: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true
    });
  });

  renderPage(1);
})();
