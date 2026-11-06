'use strict';
(() => {
  let session = null;
  let selected = null;
  let selectionCounter = 0;
  const $ = (id) => document.getElementById(id);
  const notice = $('notice');
  const form = $('brand-form');
  const campaignForm = $('campaign-form');
  const fields = ['description', 'audience', 'tone', 'language', 'constraints'];

  function message(text, error = false) {
    notice.textContent = text;
    notice.classList.toggle('error', error);
    notice.hidden = !text;
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (session) headers.set('Authorization', `Bearer ${session}`);
    if (options.body) headers.set('Content-Type', 'application/json');
    const response = await fetch(path, { ...options, headers, cache: 'no-store', credentials: 'same-origin' });
    if (!response.ok) {
      if (response.status === 401) throw new Error('Sessiya tugagan. Ilovani Telegram orqali qayta oching.');
      if (response.status === 403) throw new Error('Bu amal uchun ruxsatingiz yo‘q.');
      throw new Error('So‘rovni bajarib bo‘lmadi. Keyinroq qayta urinib ko‘ring.');
    }
    return response.json();
  }

  function setEditable(editable) {
    for (const field of fields) form.elements[field].disabled = !editable;
    $('save-button').disabled = !editable;
    if ($('generate-button')) $('generate-button').disabled = !editable;
  }

  async function selectProject(project, card) {
    const request = ++selectionCounter;
    selected = null;
    for (const item of document.querySelectorAll('.project-card')) {
      item.classList.toggle('active', item === card);
      item.setAttribute('aria-pressed', item === card ? 'true' : 'false');
    }
    $('brand-panel').hidden = false;
    if ($('campaign-panel')) $('campaign-panel').hidden = false;
    $('content-panel').hidden = true;
    $('brand-title').textContent = project.name;
    $('project-role').textContent = project.role;
    $('form-status').textContent = 'Brif yuklanmoqda…';
    for (const field of fields) form.elements[field].value = '';
    setEditable(false);

    try {
      const brand = await api(`/api/v1/projects/${encodeURIComponent(project.id)}/brand`);
      if (request !== selectionCounter) return;
      for (const field of fields) form.elements[field].value = brand[field] || '';
      selected = project;
      const editable = ['owner', 'admin', 'editor'].includes(project.role);
      setEditable(editable);
      $('form-status').textContent = editable ? '' : 'Sizda faqat ko‘rish huquqi bor.';
      $('content-panel').hidden = false;
      $('draft-form').hidden = !editable;
      $('draft-status').textContent = '';
      $('draft-form').reset();
      if ($('ai-plan-result')) $('ai-plan-result').hidden = true;
      if ($('campaign-status')) $('campaign-status').textContent = '';
      await loadContent(project, request);
    } catch (err) {
      if (request === selectionCounter) $('form-status').textContent = err.message;
    }
  }

  function renderProjects(projects) {
    const list = $('project-list');
    list.replaceChildren();
    $('project-count').textContent = `${projects.length} ta loyiha`;
    projects.forEach((project, i) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'project-card';
      card.setAttribute('aria-pressed', 'false');
      const top = document.createElement('div');
      top.className = 'card-top';
      const number = document.createElement('span');
      number.className = 'card-number';
      number.textContent = `LOYIHA / ${String(i + 1).padStart(2, '0')}`;
      const arrow = document.createElement('span');
      arrow.className = 'card-arrow';
      arrow.textContent = '↗';
      top.append(number, arrow);
      const bottom = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'card-name';
      name.textContent = project.name;
      const subtitle = document.createElement('div');
      subtitle.className = 'card-sub';
      subtitle.textContent = 'Boshqaruv va AI marketing';
      bottom.append(name, subtitle);
      card.append(top, bottom);
      card.addEventListener('click', () => selectProject(project, card));
      list.append(card);
    });
  }

  const states = {
    draft: 'Qoralama',
    awaiting_approval: 'Tasdiq kutilmoqda',
    approved: 'Tasdiqlangan ✅',
    rejected: 'Rad etilgan ❌'
  };

  async function loadContent(project, request) {
    const list = $('content-list');
    list.replaceChildren();
    const loading = document.createElement('p');
    loading.className = 'content-empty';
    loading.textContent = 'Qoralamalar yuklanmoqda…';
    list.append(loading);
    try {
      const items = await api(`/api/v1/projects/${encodeURIComponent(project.id)}/content`);
      if (request !== selectionCounter) return;
      list.replaceChildren();
      if (!items.length) {
        loading.textContent = 'Hozircha qoralama yo‘q. Yuqoridagi AI Jamoa tugmasi orqali yaratishingiz mumkin.';
        list.append(loading);
      }
      for (const item of items) renderContent(item, project, request);
    } catch (err) {
      if (request === selectionCounter) loading.textContent = err.message;
    }
  }

  function renderContent(item, project, request) {
    const article = document.createElement('article');
    article.className = 'content-item';
    const head = document.createElement('div'); head.className = 'content-head';
    const meta = document.createElement('span'); meta.className = 'content-meta';
    meta.textContent = `${item.channel.toUpperCase()} · ${item.version.number}-versiya`;
    const state = document.createElement('span'); state.className = 'content-state';
    state.textContent = states[item.state] || item.state;
    head.append(meta, state);

    if (item.version.headline) {
      const h = document.createElement('h4');
      h.style.margin = '0 0 8px 0';
      h.style.fontSize = '15px';
      h.textContent = item.version.headline;
      article.append(head, h);
    } else {
      article.append(head);
    }

    const body = document.createElement('p'); body.className = 'content-body'; body.textContent = item.version.body;
    const actions = document.createElement('div'); actions.className = 'content-actions';
    const feedback = document.createElement('p'); feedback.className = 'content-feedback';
    const canEdit = ['owner', 'admin', 'editor'].includes(project.role);
    const canApprove = ['owner', 'admin'].includes(project.role);

    function button(label, action, className = 'secondary') {
      const b = document.createElement('button'); b.type = 'button'; b.className = className; b.textContent = label;
      b.addEventListener('click', async () => {
        for (const control of actions.querySelectorAll('button')) control.disabled = true;
        feedback.textContent = '';
        try {
          const shouldReload = await action();
          if (shouldReload !== false && request === selectionCounter) await loadContent(project, request);
        } catch (err) {
          feedback.textContent = err.message;
          for (const control of actions.querySelectorAll('button')) control.disabled = false;
        }
      });
      actions.append(b);
    }

    const version = { version_id: item.version.id, checksum: item.version.checksum };
    const endpoint = `/api/v1/content/${encodeURIComponent(item.id)}`;

    if (canEdit && item.state === 'draft') {
      button('Tasdiqqa yuborish', () => api(`${endpoint}/submit-review`, { method: 'POST', body: JSON.stringify(version) }));
    }
    if (canApprove && item.state === 'awaiting_approval') {
      button('Tasdiqlash ✅', () => api(`${endpoint}/decision`, { method: 'POST', body: JSON.stringify({ ...version, approved: true }) }));
      button('Rad etish ❌', () => api(`${endpoint}/decision`, { method: 'POST', body: JSON.stringify({ ...version, approved: false }) }));
    }
    if (canEdit && ['draft', 'awaiting_approval', 'approved', 'rejected'].includes(item.state)) {
      button('Tahrirlash', async () => {
        const input = document.createElement('textarea'); input.value = item.version.body; input.rows = 5; input.maxLength = 10000;
        const save = document.createElement('button'); save.type = 'button'; save.className = 'secondary'; save.textContent = 'Yangi versiyani saqlash';
        const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'secondary'; cancel.textContent = 'Bekor qilish';
        body.replaceWith(input); actions.replaceChildren(save, cancel);
        cancel.addEventListener('click', () => loadContent(project, request));
        save.addEventListener('click', async () => {
          if (!input.value.trim()) { feedback.textContent = 'Post matnini kiriting.'; return; }
          save.disabled = true;
          try {
            await api(`${endpoint}/revise`, { method: 'POST', body: JSON.stringify({ expected_version_id: item.version.id, body: input.value }) });
            if (request === selectionCounter) await loadContent(project, request);
          } catch (err) { feedback.textContent = err.message; save.disabled = false; }
        });
        feedback.textContent = 'O‘zgartirish avvalgi tasdiqni bekor qiladi.';
        return false;
      });
    }

    article.append(body, actions, feedback);
    list.append(article);
  }

  // AI Campaign generation handler
  if (campaignForm) {
    campaignForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!selected) return;
      const project = selected;
      const request = selectionCounter;
      const objectiveInput = $('campaign-objective');
      const generateBtn = $('generate-button');
      const status = $('campaign-status');
      const planBox = $('ai-plan-result');
      const strategyText = $('ai-strategy-text');
      const missingBox = $('ai-missing-info');

      if (!objectiveInput.value.trim()) return;
      generateBtn.disabled = true;
      status.textContent = 'Orchestrator, Kopirayter va QA agentlari ishlamoqda…';

      try {
        const campaign = await api(`/api/v1/projects/${encodeURIComponent(project.id)}/campaigns`, {
          method: 'POST',
          body: JSON.stringify({
            name: `${project.name} kampaniyasi`,
            objective: objectiveInput.value.trim(),
            budget_cap: 30.0
          })
        });

        const planResult = await api(`/api/v1/projects/${encodeURIComponent(project.id)}/campaigns/${encodeURIComponent(campaign.id)}/generate-plan`, {
          method: 'POST',
          body: JSON.stringify({ objective: objectiveInput.value.trim() })
        });

        if (request === selectionCounter) {
          status.textContent = '✅ AI Jamoa 3 ta post va strategiyani tayyorladi!';
          if (planBox && strategyText) {
            planBox.hidden = false;
            strategyText.textContent = planResult.strategy;
            if (missingBox) {
              if (planResult.missing_information && planResult.missing_information.length) {
                missingBox.hidden = false;
                missingBox.innerHTML = '<strong>Eslatma ([NEEDS INPUT]):</strong><ul>' +
                  planResult.missing_information.map(m => `<li>${m}</li>`).join('') + '</ul>';
              } else {
                missingBox.hidden = true;
              }
            }
          }
          await loadContent(project, request);
        }
      } catch (err) {
        if (request === selectionCounter) status.textContent = err.message;
      } finally {
        generateBtn.disabled = false;
      }
    });
  }

  $('draft-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!selected) return;
    const project = selected, request = selectionCounter, f = event.currentTarget;
    const button = f.querySelector('button');
    if (!f.elements.body.value.trim()) return;
    button.disabled = true; $('draft-status').textContent = 'Saqlanmoqda…';
    try {
      await api(`/api/v1/projects/${encodeURIComponent(project.id)}/content`, { method: 'POST', body: JSON.stringify({ channel: 'telegram', body: f.elements.body.value }) });
      if (request === selectionCounter) { f.reset(); $('draft-status').textContent = 'Qoralama yaratildi.'; await loadContent(project, request); }
    } catch (err) { if (request === selectionCounter) $('draft-status').textContent = err.message; }
    finally { button.disabled = false; }
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!selected) return;
    const project = selected;
    const request = selectionCounter;
    const data = Object.fromEntries(fields.map(field => [field, form.elements[field].value]));
    $('save-button').disabled = true;
    $('form-status').textContent = 'Saqlanmoqda…';
    try {
      await api(`/api/v1/projects/${encodeURIComponent(project.id)}/brand`, { method: 'PUT', body: JSON.stringify(data) });
      if (request === selectionCounter) $('form-status').textContent = 'Brif saqlandi.';
    } catch (err) {
      if (request === selectionCounter) $('form-status').textContent = err.message;
    } finally {
      if (request === selectionCounter) $('save-button').disabled = false;
    }
  });

  async function start() {
    const webApp = window.Telegram && window.Telegram.WebApp;
    if (!webApp || !webApp.initData) {
      message('Bu sahifani Telegram botidagi Mini App orqali oching.', true);
      return;
    }
    webApp.ready();
    try {
      const auth = await api('/api/v1/auth/telegram', { method: 'POST', body: JSON.stringify({ init_data: webApp.initData }) });
      session = auth.access_token;
      const projects = await api('/api/v1/projects');
      renderProjects(projects);
      $('workspace').hidden = false;
      message('');
    } catch (err) {
      message(err.message, true);
    }
  }

  start();
})();
