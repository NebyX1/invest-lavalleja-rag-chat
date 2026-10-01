// The portal opts into this visual theme; the chat and administrative flows stay the same.
if (new URLSearchParams(window.location.search).get('theme') === 'invest') {
  document.documentElement.dataset.theme = 'invest'
}
