const $ = selector => document.querySelector(selector);
let state = {}, points = [], selected = null, modelState = null;
let frameUrl = null, loadingFrame = false;

async function api(path, method = 'GET', body) {
  const response = await fetch(path, {method, headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(data.error || '請求失敗');
  return data;
}

function render(nextState) {
  state = nextState;
  $('#status').textContent = state.status || '';
  $('#health').textContent = state.frozen ? '● 分析畫面已凍結' : state.coin && state.foot ? '● AI 已準備完成' : '● 等待中';
  $('#coin').textContent = state.coin ? `硬幣 ${state.coin.denomination} 元 · ${state.coin.confidence}` : '硬幣 —';
  $('#foot').textContent = state.foot ? `襪子腳 · ${state.foot.confidence}` : '襪子腳 —';
  if (state.result) $('#length').textContent = `${state.result.foot_length_mm.toFixed(1)} mm`;

  const box = $('#records');
  box.innerHTML = '';
  $('#records-count').textContent = `${(state.records || []).length} 筆`;
  (state.records || []).forEach(record => {
    const entry = document.createElement('div');
    entry.className = `record ${record.id === selected ? 'active' : ''}`;
    const details = document.createElement('div');
    const name = document.createElement('b');
    name.textContent = record.subject_name || '未命名';
    const meta = document.createElement('small');
    meta.textContent = `${record.subject_id || '未填編號'} · ${record.created_utc.slice(0, 16).replace('T', ' ')}`;
    details.append(name, meta);
    const actions = document.createElement('div');
    actions.className = 'record-actions';
    const value = document.createElement('em');
    value.textContent = `${record.foot_length_mm} mm`;
    const edit = document.createElement('button');
    edit.className = 'record-action'; edit.textContent = '編輯';
    edit.onclick = event => { event.stopPropagation(); selectRecord(record); };
    const remove = document.createElement('button');
    remove.className = 'record-action danger'; remove.textContent = '刪除';
    remove.onclick = event => { event.stopPropagation(); deleteRecord(record); };
    actions.append(value, edit, remove);
    entry.append(details, actions);
    entry.onclick = () => selectRecord(record);
    box.append(entry);
  });
}

function selectRecord(record) {
  selected = record.id;
  $('#edit-name').value = record.subject_name || '';
  $('#edit-sid').value = record.subject_id || '';
  $('#edit-note').value = record.note || '';
  $('#edit-hint').textContent = `正在編輯：${record.subject_name || '未命名'}`;
  $('#update').disabled = false;
  $('#cancel-edit').hidden = false;
  $('#delete-selected').disabled = false;
  showView('records');
  render(state);
}

function cancelEdit() {
  selected = null;
  $('#edit-hint').textContent = '選擇一筆紀錄即可編輯';
  $('#update').disabled = true;
  $('#cancel-edit').hidden = true;
  $('#delete-selected').disabled = true;
}

async function deleteRecord(record) {
  if (!confirm(`確定要刪除「${record.subject_name || '未命名'}」的量測紀錄嗎？`)) return;
  try {
    await api(`/api/records/${record.id}`, 'DELETE');
    if (selected === record.id) cancelEdit();
    await refresh();
  } catch (error) { alert(error.message); }
}

async function loadFrame(force = false) {
  if (loadingFrame || (state.frozen && !force)) return;
  loadingFrame = true;
  try {
    const response = await fetch('/api/frame.jpg', {cache: 'no-store'});
    if (!response.ok) return;
    const blob = await response.blob();
    if (!blob.size) return;
    const image = $('#frame');
    const nextUrl = URL.createObjectURL(blob);
    image.onload = () => {
      if (frameUrl) URL.revokeObjectURL(frameUrl);
      frameUrl = nextUrl;
      image.classList.add('show');
      $('#empty').style.display = 'none';
    };
    image.onerror = () => URL.revokeObjectURL(nextUrl);
    image.src = nextUrl;
  } catch (_error) {
    // Keep the last valid frame on screen while the camera reconnects.
  } finally {
    loadingFrame = false;
  }
}

async function refresh() {
  try {
    render(await api('/api/state'));
    if (!state.frozen) {
      loadFrame();
    }
  } catch (error) { $('#status').textContent = error.message; }
}

function showView(view) {
  document.querySelectorAll('.view').forEach(section => { section.hidden = section.id !== `${view}-view`; });
  document.querySelectorAll('[data-view]').forEach(link => link.classList.toggle('active', link.dataset.view === view));
  if (view === 'models') refreshModels();
}

function renderModels(data) {
  modelState = data;
  const box = $('#model-cards');
  box.innerHTML = '';
  Object.values(data).forEach(model => {
    const card = document.createElement('article');
    card.className = 'card model-card';
    card.innerHTML = `<div class="model-status ${model.available ? 'ready' : 'missing'}">${model.available ? '● 模型檔可用' : '● 找不到模型檔'}</div><h3>${model.title}</h3><code>${model.file}</code><p>可辨識：${model.classes.join('、')}</p><dl><div><dt>載入狀態</dt><dd>${model.loaded ? '已載入' : '尚未載入'}</dd></div><div><dt>目前辨識</dt><dd>${model.live_result || '尚未辨識'}</dd></div></dl>`;
    box.append(card);
  });
}

async function refreshModels() {
  try { renderModels(await api('/api/models')); }
  catch (error) { $('#model-cards').textContent = error.message; }
}

$('#start').onclick = async () => {
  try { await api('/api/start', 'POST', {url: $('#url').value}); points = []; selected = null; refresh(); }
  catch (error) { alert(error.message); }
};
$('#freeze').onclick = async () => {
  try { await api('/api/freeze', 'POST'); points = []; refresh(); }
  catch (error) { alert(error.message); }
};
$('#auto-measure').onclick = async () => {
  try {
    const result = await api('/api/auto-measure', 'POST');
    state.result = result;
    $('#length').textContent = `${result.foot_length_mm.toFixed(1)} mm`;
    $('#status').textContent = '已自動計算腳長，請確認量測線後儲存';
    loadFrame(true);
  } catch (error) { alert(error.message); }
};
$('#frame').onclick = async event => {
  if (!state.frozen || points.length >= 4 || !state.image_size) return;
  const bounds = event.target.getBoundingClientRect(), [width, height] = state.image_size;
  points.push([(event.clientX - bounds.left) * width / bounds.width, (event.clientY - bounds.top) * height / bounds.height]);
  drawPoints();
  if (points.length === 4) {
    try {
      const result = await api('/api/measure', 'POST', {points});
      state.result = result;
      $('#length').textContent = `${result.foot_length_mm.toFixed(1)} mm`;
      $('#status').textContent = '量測完成，請填寫右側資料並儲存';
      loadFrame(true);
    } catch (error) { alert(error.message); points = []; drawPoints(); }
  }
};
function drawPoints() {
  const svg = $('#points'), image = $('#frame');
  svg.innerHTML = '';
  const bounds = image.getBoundingClientRect();
  points.forEach((point, index) => {
    const x = point[0] * bounds.width / (state.image_size?.[0] || 1);
    const y = point[1] * bounds.height / (state.image_size?.[1] || 1);
    svg.innerHTML += `<circle cx="${x}" cy="${y}" r="7" fill="#d7f46a"/><text x="${x + 12}" y="${y - 10}" fill="white" font-size="15" font-weight="bold">${index + 1}</text>`;
  });
}
$('#save').onclick = async () => {
  try { const record = await api('/api/records', 'POST', {subject_name: $('#name').value, subject_id: $('#sid').value, note: $('#note').value}); selected = record.id; refresh(); }
  catch (error) { alert(error.message); }
};
$('#update').onclick = async () => {
  if (!selected) return alert('請先從右側量測紀錄選擇一筆資料');
  try { await api(`/api/records/${selected}`, 'POST', {subject_name: $('#edit-name').value, subject_id: $('#edit-sid').value, note: $('#edit-note').value}); cancelEdit(); refresh(); }
  catch (error) { alert(error.message); }
};
$('#cancel-edit').onclick = cancelEdit;
$('#delete-selected').onclick = async () => {
  if (!selected) return;
  const record = (state.records || []).find(item => item.id === selected);
  if (record) await deleteRecord(record);
};
document.querySelectorAll('[data-view]').forEach(link => link.onclick = () => showView(link.dataset.view));
setInterval(refresh, 900);
refresh();
