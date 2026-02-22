function setCookie(name, value) {
  const expires = new Date(Date.now() + 30).toUTCString();
  document.cookie =
    name +
    '=' +
    encodeURIComponent(value) +
    '; expires=' +
    expires +
    '; path=/; SameSite=Lax';
}

function getCookie(name) {
  return document.cookie
    .split('; ')
    .find(row => row.startsWith(name + '='))?.split('=')[1];
}

function acknowledgePaymentAlert() {
  document.querySelectorAll('[data-account]').forEach(el => {
    setCookie(`payment_alert_ack_${el.dataset.account}`, '1');
  });
  document.getElementById('payment-alert-overlay')?.remove();
}

(function () {
  const alerts = document.querySelectorAll('[data-account]');
  if (!alerts.length) return;

  const allAck = [...alerts].every(el =>
    getCookie(`payment_alert_ack_${el.dataset.account}`)
  );

  if (allAck) {
    document.getElementById('payment-alert-overlay')?.remove();
  }
})();
