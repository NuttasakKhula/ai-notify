(() => {
  const slides = [...document.querySelectorAll('.slide')];
  const toc = document.querySelector('#toc');
  const controls = document.querySelector('.deck-controls');
  const toggle = document.querySelector('#present');
  let current = Math.max(0, slides.findIndex(slide => '#' + slide.id === location.hash));
  let presenting = false;
  let group = '';
  const links = slides.map((slide, index) => {
    if (slide.dataset.group !== group) {
      group = slide.dataset.group;
      const label = document.createElement('div');
      label.className = 'nav-group';
      label.textContent = group;
      toc.append(label);
    }
    const link = document.createElement('a');
    link.href = '#' + slide.id;
    const number = document.createElement('span');
    number.textContent = String(index).padStart(2, '0');
    link.append(number, document.createTextNode(slide.dataset.title));
    toc.append(link);
    return link;
  });
  function update() {
    slides.forEach((slide, index) => {
      slide.classList.toggle('current', index === current);
      if (index === current) links[index].setAttribute('aria-current', 'location');
      else links[index].removeAttribute('aria-current');
    });
    document.querySelector('#counter').textContent = `${current + 1} / ${slides.length}`;
    document.querySelector('#prev').disabled = current === 0;
    document.querySelector('#next').disabled = current === slides.length - 1;
  }
  function go(index) {
    current = Math.max(0, Math.min(slides.length - 1, index));
    update();
    history.replaceState(null, '', '#' + slides[current].id);
    window.scrollTo({top: 0, behavior: 'instant'});
  }
  function setPresentation(value) {
    presenting = value;
    document.body.classList.toggle('presenting', value);
    controls.hidden = !value;
    toggle.setAttribute('aria-pressed', String(value));
    toggle.textContent = value ? '▤ โหมดอ่านคู่มือ' : '▷ โหมดนำเสนอ';
    update();
    if (value) window.scrollTo({top: 0, behavior: 'instant'});
    else {
      slides[current].scrollIntoView({behavior: 'instant'});
      toggle.focus({preventScroll: true});
    }
  }
  toggle.addEventListener('click', () => setPresentation(!presenting));
  document.querySelector('#exit').addEventListener('click', () => setPresentation(false));
  document.querySelector('#prev').addEventListener('click', () => go(current - 1));
  document.querySelector('#next').addEventListener('click', () => go(current + 1));
  document.querySelector('#print').addEventListener('click', () => window.print());
  document.addEventListener('keydown', event => {
    if (!presenting || event.altKey || event.ctrlKey || event.metaKey || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) return;
    if (event.key === 'Escape') setPresentation(false);
    else if (['ArrowRight', 'PageDown', 'ArrowLeft', 'PageUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      go(event.key === 'Home' ? 0 : event.key === 'End' ? slides.length - 1 : current + (['ArrowRight', 'PageDown'].includes(event.key) ? 1 : -1));
    }
  });
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href^="#"]');
    if (!link) return;
    const index = slides.findIndex(slide => '#' + slide.id === link.getAttribute('href'));
    if (index < 0) return;
    current = index;
    update();
    if (presenting) { event.preventDefault(); go(index); }
  });
  window.addEventListener('hashchange', () => {
    const index = slides.findIndex(slide => '#' + slide.id === location.hash);
    if (index >= 0) { current = index; update(); }
  });
  let scheduled = false;
  window.addEventListener('scroll', () => {
    if (presenting || scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      current = slides.reduce((best, slide, index) => slide.getBoundingClientRect().top <= 150 ? index : best, 0);
      update();
      scheduled = false;
    });
  }, {passive: true});
  update();
})();
