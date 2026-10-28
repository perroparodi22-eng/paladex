/* Aijo Nails Torino — interazioni del sito */
(() => {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Menu su smartphone */
  const toggle = document.querySelector('.menu-toggle');
  const nav = document.getElementById('menu');

  const setMenu = (open) => {
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Chiudi il menu' : 'Apri il menu');
    nav.classList.toggle('is-open', open);
  };

  if (toggle && nav) {
    toggle.addEventListener('click', () => {
      setMenu(toggle.getAttribute('aria-expanded') !== 'true');
    });
    nav.addEventListener('click', (event) => {
      if (event.target.closest('a')) setMenu(false);
    });
    document.addEventListener('click', (event) => {
      if (!event.target.closest('.header-inner')) setMenu(false);
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
        setMenu(false);
        toggle.focus();
      }
    });
  }

  /* Schede del listino */
  const tablist = document.querySelector('[role="tablist"]');
  if (tablist) {
    const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
    const panels = tabs.map((tab) => document.getElementById(tab.getAttribute('aria-controls')));

    const select = (index, focus) => {
      tabs.forEach((tab, i) => {
        const active = i === index;
        tab.setAttribute('aria-selected', String(active));
        tab.tabIndex = active ? 0 : -1;
        panels[i].hidden = !active;
      });
      if (focus) tabs[index].focus();
    };

    tabs.forEach((tab, i) => {
      tab.addEventListener('click', () => select(i, false));
      tab.addEventListener('keydown', (event) => {
        const keys = {
          ArrowRight: (i + 1) % tabs.length,
          ArrowDown: (i + 1) % tabs.length,
          ArrowLeft: (i - 1 + tabs.length) % tabs.length,
          ArrowUp: (i - 1 + tabs.length) % tabs.length,
          Home: 0,
          End: tabs.length - 1,
        };
        if (event.key in keys) {
          event.preventDefault();
          select(keys[event.key], true);
        }
      });
    });

    panels.forEach((panel) => (panel.tabIndex = 0));
    tablist.hidden = false;
    select(0, false);
  }

  /* Barra "Prenota" in basso: compare dopo aver superato i bottoni iniziali */
  const bar = document.querySelector('.mobile-bar');
  const heroActions = document.querySelector('.hero-actions');
  if (bar && heroActions && 'IntersectionObserver' in window) {
    new IntersectionObserver(([entry]) => {
      bar.classList.toggle('is-visible', !entry.isIntersecting && entry.boundingClientRect.top < 0);
    }).observe(heroActions);
  } else if (bar) {
    bar.classList.add('is-visible');
  }

  /* Ombra dell'header durante lo scroll */
  const header = document.querySelector('.site-header');
  if (header) {
    const onScroll = () => header.classList.toggle('is-scrolled', window.scrollY > 8);
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  /* Comparsa morbida degli elementi */
  const reveals = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && !reduceMotion) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      },
      { rootMargin: '0px 0px -8% 0px' }
    );
    reveals.forEach((el) => observer.observe(el));
  } else {
    reveals.forEach((el) => el.classList.add('is-visible'));
  }

  /* Logo che si inclina seguendo il mouse (solo desktop) */
  const art = document.querySelector('.hero-art');
  if (art && !reduceMotion && window.matchMedia('(pointer: fine)').matches) {
    art.addEventListener('pointermove', (event) => {
      const rect = art.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width - 0.5;
      const y = (event.clientY - rect.top) / rect.height - 0.5;
      art.style.setProperty('--tx', `${(x * 14).toFixed(2)}deg`);
      art.style.setProperty('--ty', `${(-y * 14).toFixed(2)}deg`);
    });
    art.addEventListener('pointerleave', () => {
      art.style.setProperty('--tx', '0deg');
      art.style.setProperty('--ty', '0deg');
    });
  }

  /* Anno nel footer */
  document.querySelectorAll('[data-year]').forEach((el) => {
    el.textContent = new Date().getFullYear();
  });
})();
