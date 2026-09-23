// Shared admin behaviour: confirm dialogs for destructive forms.
document.addEventListener("submit", (e) => {
  const msg = (e.submitter && e.submitter.dataset.confirm) || e.target.dataset.confirm;
  if (msg && !window.confirm(msg)) e.preventDefault();
});
