const hamburgerBtn = document.getElementById('hamburger-btn');
const hamburgerMenu = document.getElementById('hamburger-menu');

hamburgerBtn.addEventListener('click', () => {
hamburgerMenu.style.display = hamburgerMenu.style.display === 'flex' ? 'none' : 'flex';
});

// Close menu if clicked outside
document.addEventListener('click', (e) => {
if (!hamburgerBtn.contains(e.target) && !hamburgerMenu.contains(e.target)) {
  hamburgerMenu.style.display = 'none';
}
});