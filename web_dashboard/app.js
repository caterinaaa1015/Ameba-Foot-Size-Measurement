const $ = selector => document.querySelector(selector);
let state = {}, points = [], selected = null;
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
  (state.records || []).forEach(record => {
    const entry = document.createElement('div');
    entry.className = `record ${record.id === selected ? 'active' : ''}`;
    entry.innerHTML = `<div><b>${record.subject_name || '未命名'}</b><small>${record.subject_id || '未填編號'} · ${record.created_utc.slice(0, 16).replace('T', ' ')}</small></div><em>${record.foot_length_mm} mm</em>`;
    entry.onclick = () => {
      selected = record.id;
      $('#name').value = record.subject_name;
      $('#sid').value = record.subject_id || '';
      $('#note').value = record.note || '';
      render(state);
    };
    box.append(entry);
  });
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
  try { await api(`/api/records/${selected}`, 'POST', {subject_name: $('#name').value, subject_id: $('#sid').value, note: $('#note').value}); refresh(); }
  catch (error) { alert(error.message); }
};
setInterval(refresh, 900);
refresh();
