document.querySelectorAll('[data-step]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-step]').forEach(tab => {
        const selected = tab === button;
        tab.setAttribute('aria-selected', String(selected));
        document.getElementById('demo-'+tab.dataset.step).classList.toggle('hidden', !selected);
    });
}));
