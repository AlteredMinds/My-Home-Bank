(function () {
  const txItems = Array.from(document.querySelectorAll('.tx-item'));
  const buttons = Array.from(document.querySelectorAll('.tx-filter-btn'));
  const pagination = document.getElementById('tx-pagination');

  if (!buttons.length) return;

  let currentFilter = buttons[0].dataset.acc;
  let currentPage = 1;
  const perPage = 10;

  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      buttons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentFilter = btn.dataset.acc;
      renderPage(1);
    });
  });

  buttons[0].classList.add('active');

  function renderPage(page) {
    currentPage = page;

    const filtered = txItems.filter(
      item => item.dataset.acc === currentFilter
    );

    const totalPages = Math.ceil(filtered.length / perPage);
    const start = (page - 1) * perPage;
    const end = start + perPage;

    txItems.forEach(item => (item.style.display = 'none'));
    filtered.forEach((item, i) => {
      item.style.display = i >= start && i < end ? 'flex' : 'none';
    });

    renderPagination(totalPages);
  }

  function renderPagination(totalPages) {
    pagination.innerHTML = '';
    if (totalPages <= 1) return;

    for (let i = 1; i <= totalPages; i++) {
      const btn = document.createElement('button');
      btn.textContent = i;
      btn.addEventListener('click', () => renderPage(i));
      pagination.appendChild(btn);
    }
  }

  renderPage(1);
})();
