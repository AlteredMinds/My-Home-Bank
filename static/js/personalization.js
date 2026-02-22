(function () {
  const theme = localStorage.getItem('theme') || 'default';
  const bg = localStorage.getItem('bgEnabled') === 'true';

  document.body.classList.add(`theme-${theme}`);
  if (bg) document.body.classList.add('bg-enabled');
})();

(function () {
  function updateBackground() {
    const bgEnabled = localStorage.getItem('bgEnabled') === 'true';
    const bgUrl = getComputedStyle(document.body)
      .getPropertyValue('--bg-image')
      .trim();

    if (bgEnabled && bgUrl && bgUrl !== 'none') {
      document.body.style.backgroundImage = bgUrl;
    } else {
      document.body.style.backgroundImage = 'none';
    }
  }

  updateBackground();
})();