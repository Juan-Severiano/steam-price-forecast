import { demoCatalog } from './demo.js';

const $ = (selector) => document.querySelector(selector);
const money = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const dateShort = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'short', timeZone: 'UTC' });
const dateFull = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' });
const DAY = 86_400_000;
const state = { catalog: demoCatalog, selected: demoCatalog.jogos[0].appid, horizon: 30, query: '', filter: 'all' };
const cleanText = (value) => String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const normalized = (value) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
const price = (value) => Number.isFinite(value) ? money.format(value) : 'Indisponível';
const dateValue = (value) => new Date(`${value}T00:00:00Z`);
const formatDate = (value, short = false) => (short ? dateShort : dateFull).format(dateValue(value));
const coverUrl = (appid) => `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${appid}/header.jpg`;
const selectedGame = () => state.catalog.jogos.find((game) => game.appid === state.selected);
const isDemo = () => state.catalog.modo === 'demo';
let currentChart = null;

function visibleGames() {
  const query = normalized(state.query.trim());
  return state.catalog.jogos.filter((game) => normalized(game.titulo).includes(query)
    && (state.filter !== 'budget' || (Number.isFinite(game.preco_atual) && game.preco_atual <= 60)));
}

function renderCatalog() {
  const games = visibleGames();
  $('#catalog-count').textContent = games.length === state.catalog.jogos.length ? games.length : `${games.length}/${state.catalog.jogos.length}`;
  $('#search-empty').hidden = games.length > 0;
  $('#games-list').replaceChildren();
  const fragment = document.createDocumentFragment();
  games.forEach((game) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `game-row${game.appid === state.selected ? ' is-selected' : ''}`;
    button.dataset.appid = String(game.appid);
    button.setAttribute('aria-pressed', String(game.appid === state.selected));
    button.setAttribute('aria-label', `${game.titulo}, ${price(game.preco_atual)}${isDemo() ? ', valor simulado' : ', na data-base'}`);
    const thumb = document.createElement('span');
    thumb.className = 'game-thumb';
    thumb.dataset.initials = game.titulo.split(/\s+/).map((part) => part[0]).slice(0, 2).join('');
    thumb.setAttribute('aria-hidden', 'true');
    const img = document.createElement('img');
    img.src = coverUrl(game.appid);
    img.alt = '';
    img.loading = 'lazy';
    img.referrerPolicy = 'no-referrer';
    img.addEventListener('error', () => { img.hidden = true; });
    thumb.append(img);
    const details = document.createElement('span');
    const name = document.createElement('span');
    name.className = 'game-row-title';
    name.textContent = game.titulo;
    const value = document.createElement('span');
    value.className = 'game-row-price';
    value.textContent = price(game.preco_atual);
    details.append(name, value);
    button.append(thumb, details);
    button.addEventListener('click', () => {
      state.selected = game.appid;
      document.querySelectorAll('.game-row').forEach((row) => {
        const active = Number(row.dataset.appid) === game.appid;
        row.classList.toggle('is-selected', active);
        row.setAttribute('aria-pressed', String(active));
      });
      renderDetail();
    });
    fragment.append(button);
  });
  $('#games-list').append(fragment);
  $('#catalog-note').textContent = isDemo()
    ? `${state.catalog.jogos.length} jogos para experimentar. Valores fictícios, capas da Steam.`
    : `${state.catalog.jogos.length} jogos no arquivo local. Preços na data-base de cada jogo.`;
}

function gameHistory(game) {
  if (!game.historico.length) return [];
  const latest = Date.parse(`${game.historico.at(-1).data}T00:00:00Z`);
  return game.historico.filter((point) => Date.parse(`${point.data}T00:00:00Z`) >= latest - 180 * DAY);
}

function renderDetail() {
  const game = selectedGame();
  if (!game) return;
  const prediction = game.previsoes?.[state.horizon];
  const baseDate = prediction?.data_base || game.data_base || game.historico.at(-1)?.data;
  $('#selected-title').textContent = game.titulo;
  $('#game-category').textContent = game.categoria || 'CATÁLOGO LOCAL · PREÇOS EM REAIS';
  $('#game-banner').style.backgroundColor = game.cor || '#294654';
  const cover = $('#selected-cover');
  cover.hidden = false;
  cover.src = coverUrl(game.appid);
  cover.onerror = () => { cover.hidden = true; };
  $('#steam-link').href = `https://store.steampowered.com/app/${game.appid}/`;
  $('#steam-link').setAttribute('aria-label', `Ver ${game.titulo} na Steam`);
  $('#game-data-label').textContent = isDemo() ? 'EXEMPLO SIMULADO' : 'ARQUIVO LOCAL';
  $('#current-price-label').textContent = isDemo() ? 'PREÇO NO EXEMPLO' : 'PREÇO NA DATA-BASE';
  $('#current-price').textContent = price(game.preco_atual);
  const discount = Number.isFinite(game.desconto_atual) ? game.desconto_atual : 0;
  $('#current-discount').hidden = discount <= 0 || !Number.isFinite(game.preco_atual);
  $('#current-discount').textContent = `−${Math.round(discount)}%`;
  $('#regular-price').innerHTML = discount > 0 && Number.isFinite(game.preco_regular)
    ? `Preço cheio <s>${cleanText(price(game.preco_regular))}</s>`
    : Number.isFinite(game.preco_atual) ? 'Sem desconto na data-base' : 'Fora da loja na data-base';
  $('#prediction-panel').hidden = !prediction;
  $('#prediction-empty').hidden = Boolean(prediction);
  if (prediction) {
    const percent = Math.round(prediction.probabilidade_desconto * 100);
    $('#chance-value').innerHTML = `${percent}<span>%</span>`;
    $('#chance-fill').style.width = `${percent}%`;
    $('#chance-description').textContent = `de um preço menor nos próximos ${state.horizon} dias.`;
    $('#minimum-range').innerHTML = `${cleanText(price(prediction.preco_minimo_p10))} <span>–</span> ${cleanText(price(prediction.preco_minimo_p90))}`;
    const interval = prediction.preco_minimo_p90 - prediction.preco_minimo_p10;
    const medianPosition = interval > 0 ? 100 * (prediction.preco_minimo_p50 - prediction.preco_minimo_p10) / interval : 50;
    $('#median-tick').style.left = `${Math.max(0, Math.min(100, medianPosition))}%`;
    $('#median-description').innerHTML = `Estimativa central (P50): <strong>${cleanText(price(prediction.preco_minimo_p50))}</strong>`;
  }
  const history = gameHistory(game);
  $('#chart-subtitle').textContent = `${isDemo() ? 'Histórico ilustrativo' : 'Fechamento diário · arquivo local'}${history.length > 1 ? ` · ${formatDate(history[0].data, true)} a ${formatDate(history.at(-1).data, true)}` : ''}`;
  $('#chart-caption').textContent = prediction
    ? 'A faixa indica o menor preço ao comprar na data-base ou esperar. Não é uma trajetória nem uma promessa de desconto. P10–P90 é uma faixa nominal de 80%, ainda sujeita à calibração.'
    : 'O histórico mostra o preço no fechamento de cada dia. Interrupções na linha indicam dias em que o jogo estava indisponível; não representam preço zero.';
  $('#base-date').textContent = baseDate ? `${isDemo() ? 'Base do exemplo' : 'Data-base'}: ${formatDate(baseDate)}` : 'Data-base não disponível';
  $('#detail-origin').textContent = isDemo() ? 'Dados sintéticos · sem cotação ao vivo' : 'Histórico local · sem cotação ao vivo';
  renderChart(game, history, prediction);
  renderHistoryTable(history);
}

function renderHistoryTable(history) {
  // Keep every change, plus the first and last day, for a useful accessible view.
  const changes = history.filter((point, index) => index === 0 || index === history.length - 1
    || point.preco !== history[index - 1].preco || point.regular !== history[index - 1].regular);
  const tbody = $('#history-table-body');
  tbody.replaceChildren();
  for (const point of changes) {
    const row = document.createElement('tr');
    for (const text of [formatDate(point.data), price(point.preco), price(point.regular)]) {
      const cell = document.createElement('td');
      cell.textContent = text;
      row.append(cell);
    }
    tbody.append(row);
  }
  $('#history-table-caption').textContent = history.length
    ? 'Mudanças de preço e última data do período exibido. Datas em UTC.'
    : 'Nenhum histórico disponível neste arquivo.';
}

function renderChart(game, history, prediction) {
  const svg = $('#price-chart');
  $('#chart-tooltip').hidden = true;
  const valid = history.filter((point) => Number.isFinite(point.preco));
  if (!valid.length) {
    svg.innerHTML = '<title id="chart-svg-title">Sem histórico de preço</title><desc id="chart-svg-description">Nenhum preço disponível para desenhar o gráfico.</desc><text x="400" y="124" text-anchor="middle" fill="#a4b6c7" font-size="14">Nenhum histórico de preço disponível.</text>';
    currentChart = null;
    return;
  }
  const left = 57, top = 31, bottom = 207, right = prediction ? 587 : 776;
  const start = Date.parse(`${history[0].data}T00:00:00Z`);
  const end = Date.parse(`${history.at(-1).data}T00:00:00Z`);
  const duration = Math.max(DAY, end - start);
  const maxPrice = Math.max(...valid.map((point) => point.preco), prediction?.preco_minimo_p90 || 0, 1);
  const ceiling = maxPrice * 1.14;
  const x = (date) => left + (Date.parse(`${date}T00:00:00Z`) - start) / duration * (right - left);
  const y = (value) => bottom - value / ceiling * (bottom - top);
  let markup = `<title id="chart-svg-title">${cleanText(game.titulo)}: histórico ${isDemo() ? 'simulado' : 'local'} de preço${prediction ? ` e faixa do menor preço em ${state.horizon} dias` : ''}</title><desc id="chart-svg-description">${cleanText(`De ${formatDate(history[0].data)} a ${formatDate(history.at(-1).data)}. Último preço disponível ${price(valid.at(-1).preco)}. ${prediction ? `Faixa nominal P10 a P90 de ${price(prediction.preco_minimo_p10)} a ${price(prediction.preco_minimo_p90)}, mediana ${price(prediction.preco_minimo_p50)}. A faixa se refere ao menor preço no período, não a uma trajetória.` : 'Sem previsão neste horizonte.'} A tabela abaixo contém os valores.`)}</desc><defs><linearGradient id="chart-history-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#76c9f3" stop-opacity=".15"/><stop offset="100%" stop-color="#76c9f3" stop-opacity=".01"/></linearGradient></defs>`;
  for (let i = 0; i <= 3; i++) {
    const value = ceiling * i / 3;
    const yy = y(value);
    markup += `<line class="chart-grid-line" x1="${left}" y1="${yy}" x2="776" y2="${yy}"/><text class="chart-axis-label" x="46" y="${yy + 3}" text-anchor="end">${money.format(value).replace(/\s/g, '').replace(',00', '')}</text>`;
  }
  const segments = [];
  let segment = [];
  for (const point of history) {
    if (Number.isFinite(point.preco)) segment.push(point);
    else if (segment.length) { segments.push(segment); segment = []; }
  }
  if (segment.length) segments.push(segment);
  for (const points of segments) {
    let d = `M${x(points[0].data).toFixed(2)},${y(points[0].preco).toFixed(2)}`;
    for (const point of points.slice(1)) d += `H${x(point.data).toFixed(2)}V${y(point.preco).toFixed(2)}`;
    const lastX = x(points.at(-1).data), firstX = x(points[0].data);
    markup += `<path d="${d}V${bottom}H${firstX}Z" fill="url(#chart-history-fill)"/><path class="chart-line" d="${d}"/>`;
    if (points.length === 1) markup += `<circle class="chart-point" cx="${lastX}" cy="${y(points[0].preco)}" r="3"/>`;
  }
  const last = history.at(-1);
  if (Number.isFinite(last.preco)) markup += `<circle class="chart-point" cx="${x(last.data)}" cy="${y(last.preco)}" r="4"/>`;
  for (let i = 0; i <= 3; i++) {
    const time = start + duration * i / 3;
    const label = dateShort.format(new Date(time));
    markup += `<text class="chart-axis-label" x="${left + (right - left) * i / 3}" y="231" text-anchor="${i === 0 ? 'start' : i === 3 ? 'end' : 'middle'}">${cleanText(label)}</text>`;
  }
  if (prediction) {
    const rangeLeft = 625, rangeRight = 760;
    const yTop = y(prediction.preco_minimo_p90), yBottom = y(prediction.preco_minimo_p10);
    markup += `<rect x="${right + 16}" y="16" width="173" height="200" fill="#b9de7406"/><line class="chart-separator" x1="${right + 15}" y1="20" x2="${right + 15}" y2="217"/><text class="chart-axis-caption" x="694" y="14" text-anchor="middle">PRÓXIMOS ${state.horizon} DIAS</text><rect class="chart-range" x="${rangeLeft}" y="${yTop}" width="${rangeRight - rangeLeft}" height="${Math.max(1, yBottom - yTop)}" rx="2"/><line class="chart-mid" x1="${rangeLeft}" x2="${rangeRight}" y1="${y(prediction.preco_minimo_p50)}" y2="${y(prediction.preco_minimo_p50)}"/><circle cx="${(rangeLeft + rangeRight) / 2}" cy="${y(prediction.preco_minimo_p50)}" r="3.5" fill="#b9de74"/><text class="chart-axis-caption" x="694" y="231" text-anchor="middle">MENOR PREÇO · P10–P90</text>`;
  }
  svg.innerHTML = markup;
  currentChart = { history, start, duration, left, right, x, y };
}

$('#price-chart').addEventListener('pointermove', (event) => {
  if (!currentChart || event.pointerType === 'touch') return;
  const chart = currentChart;
  const rect = event.currentTarget.getBoundingClientRect();
  const localX = (event.clientX - rect.left) / rect.width * 800;
  if (localX < chart.left || localX > chart.right) { $('#chart-tooltip').hidden = true; return; }
  const target = chart.start + (localX - chart.left) / (chart.right - chart.left) * chart.duration;
  const point = chart.history.reduce((best, current) => Math.abs(Date.parse(`${current.data}T00:00:00Z`) - target)
    < Math.abs(Date.parse(`${best.data}T00:00:00Z`) - target) ? current : best);
  const tooltip = $('#chart-tooltip');
  tooltip.innerHTML = `${cleanText(formatDate(point.data))}<strong>${cleanText(price(point.preco))}</strong>`;
  tooltip.style.left = `${Math.max(75, Math.min(rect.width - 75, chart.x(point.data) / 800 * rect.width))}px`;
  tooltip.style.top = `${Number.isFinite(point.preco) ? Math.max(54, chart.y(point.preco) / 255 * rect.height - 12) : 75}px`;
  tooltip.hidden = false;
});
$('#price-chart').addEventListener('pointerleave', () => { $('#chart-tooltip').hidden = true; });

function renderMode() {
  $('#mode-badge').textContent = isDemo() ? 'DEMONSTRAÇÃO' : 'DADOS LOCAIS';
  $('#mode-description').textContent = isDemo()
    ? 'Preços e previsões simulados para explorar a interface.'
    : 'Arquivo aberto apenas nesta aba. Preços na data-base, sem atualização ao vivo.';
  $('#restore-demo').hidden = isDemo();
}

function filterChanged() {
  const games = visibleGames();
  if (games.length && !games.some((game) => game.appid === state.selected)) {
    state.selected = games[0].appid;
    renderDetail();
  }
  renderCatalog();
}
$('#game-search').addEventListener('input', (event) => { state.query = event.target.value; filterChanged(); });
document.querySelectorAll('[data-filter]').forEach((button) => button.addEventListener('click', () => {
  state.filter = button.dataset.filter;
  document.querySelectorAll('[data-filter]').forEach((item) => {
    const active = item.dataset.filter === state.filter;
    item.classList.toggle('is-active', active);
    item.setAttribute('aria-pressed', String(active));
  });
  filterChanged();
}));
function resetFilters() {
  state.query = '';
  state.filter = 'all';
  $('#game-search').value = '';
  document.querySelectorAll('[data-filter]').forEach((button) => {
    const active = button.dataset.filter === 'all';
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}
$('#clear-search').addEventListener('click', () => { resetFilters(); filterChanged(); $('#game-search').focus(); });
document.querySelectorAll('[data-horizon]').forEach((button) => button.addEventListener('click', () => {
  state.horizon = Number(button.dataset.horizon);
  document.querySelectorAll('[data-horizon]').forEach((item) => {
    const active = Number(item.dataset.horizon) === state.horizon;
    item.classList.toggle('is-active', active);
    item.setAttribute('aria-pressed', String(active));
  });
  renderDetail();
}));

function validDate(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(`${value}T00:00:00Z`))
    && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}
function optionalPrice(value) { return value === null || (Number.isFinite(value) && value >= 0); }
function samePrice(a, b) { return a === b || (Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) < 1e-8); }
function validateCatalog(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) || input.schema_version !== 1
    || input.moeda !== 'BRL' || !Array.isArray(input.jogos) || input.jogos.length === 0 || input.jogos.length > 5000) {
    throw new Error('Use um catálogo schema_version 1, em BRL, com 1 a 5.000 jogos, exportado pelo projeto.');
  }
  const ids = new Set();
  const games = input.jogos.map((game, index) => {
    const fail = () => { throw new Error(`O jogo ${index + 1} tem campos inválidos. Exporte o catálogo novamente pelo projeto.`); };
    if (!game || !Number.isSafeInteger(game.appid) || game.appid <= 0 || ids.has(game.appid)
      || typeof game.titulo !== 'string' || !game.titulo.trim() || game.titulo.length > 200
      || !optionalPrice(game.preco_atual) || !optionalPrice(game.preco_regular)
      || !Array.isArray(game.historico) || game.historico.length > 10000) fail();
    ids.add(game.appid);
    let previous = '';
    const history = game.historico.map((point) => {
      if (!point || !validDate(point.data) || point.data <= previous || !optionalPrice(point.preco) || !optionalPrice(point.regular)) fail();
      previous = point.data;
      return { data: point.data, preco: point.preco, regular: point.regular };
    });
    const lastDay = history.at(-1);
    const baseDate = game.data_base ?? lastDay?.data;
    if ((game.data_base != null && !validDate(game.data_base))
      || (lastDay && (baseDate !== lastDay.data || !samePrice(game.preco_atual, lastDay.preco)
        || !samePrice(game.preco_regular, lastDay.regular)))
      || (!lastDay && (game.preco_atual !== null || game.preco_regular !== null))) fail();
    const predictions = {};
    for (const horizon of [30, 90]) {
      const pred = game.previsoes?.[horizon];
      if (!pred) continue;
      const quantiles = [pred.preco_minimo_p10, pred.preco_minimo_p50, pred.preco_minimo_p90];
      if (!Number.isFinite(game.preco_atual) || !Number.isFinite(pred.probabilidade_desconto)
        || pred.probabilidade_desconto < 0 || pred.probabilidade_desconto > 1
        || !validDate(pred.data_base) || pred.data_base !== baseDate || !lastDay || quantiles.some((value) => !Number.isFinite(value) || value < 0)
        || quantiles[0] > quantiles[1] || quantiles[1] > quantiles[2]
        || quantiles[2] > game.preco_atual + 0.011) fail();
      predictions[horizon] = {
        probabilidade_desconto: pred.probabilidade_desconto,
        preco_minimo_p10: quantiles[0], preco_minimo_p50: quantiles[1], preco_minimo_p90: quantiles[2], data_base: pred.data_base,
      };
    }
    return {
      appid: game.appid, titulo: game.titulo.trim(), preco_atual: game.preco_atual, preco_regular: game.preco_regular,
      desconto_atual: Number.isFinite(game.desconto_atual) ? Math.min(100, Math.max(0, game.desconto_atual)) : null,
      historico: history, previsoes: predictions,
      data_base: baseDate,
    };
  });
  // Imported data never becomes public, persistent, or executable.
  return { schema_version: 1, modo: input.modo === 'demo' ? 'demo' : 'local', moeda: 'BRL', jogos: games };
}
function showFeedback(message, error = false) {
  $('#import-feedback').textContent = message;
  $('#import-feedback').classList.toggle('error', error);
}
for (const id of ['#import-button', '#import-button-bottom']) $(id).addEventListener('click', () => { $('#import-file').click(); });
$('#import-file').addEventListener('change', async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    if (file.size > 64 * 1024 * 1024) throw new Error('O arquivo excede 64 MB. Exporte um catálogo com um histórico mais curto.');
    showFeedback('Lendo o arquivo nesta aba…');
    const catalog = validateCatalog(JSON.parse(await file.text()));
    state.catalog = catalog;
    state.selected = catalog.jogos[0].appid;
    resetFilters();
    renderMode();
    renderCatalog();
    renderDetail();
    showFeedback(`${catalog.jogos.length} ${catalog.jogos.length === 1 ? "jogo aberto" : "jogos abertos"}. O arquivo, os preços e as previsões não foram enviados a um servidor.`);
    $('#explorar').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
  } catch (error) {
    showFeedback(error instanceof SyntaxError ? 'O arquivo não é um JSON válido. Selecione o catálogo exportado pelo projeto.' : error.message || 'Não foi possível ler este arquivo.', true);
  } finally { event.target.value = ''; }
});
$('#restore-demo').addEventListener('click', () => {
  state.catalog = demoCatalog;
  state.selected = demoCatalog.jogos[0].appid;
  resetFilters();
  renderMode(); renderCatalog(); renderDetail();
  showFeedback('Demonstração restaurada. O catálogo local foi removido desta aba.');
});

const transcript = [
  { kind: 'note', text: '# demonstração com dados sintéticos · nenhuma chamada à API' },
  { kind: 'command', text: 'uv run steam-forecast jogos-universo' },
  { kind: 'output', text: 'Preparando a lista de jogos da Steam…' },
  { kind: 'success', text: '✓ universo do exemplo: 8 jogos' },
  { kind: 'command', text: 'uv run steam-forecast jogos-coletar' },
  { kind: 'output', text: 'Lendo mudanças de preço; retomando o cache local…' },
  { kind: 'success', text: '✓ histórico ilustrativo pronto · dados fora do Git' },
  { kind: 'command', text: 'uv run steam-forecast jogos-avaliar --horizonte 30 --horizonte 90' },
  { kind: 'output', text: 'Séries diárias → treino com alvos já conhecidos → teste futuro' },
  { kind: 'output', text: 'Comparação: regras simples × gradient boosting' },
  { kind: 'note', text: '# resultados reais dependem da avaliação; esta tela não os inventa' },
  { kind: 'command', text: 'uv run steam-forecast jogos-exportar' },
  { kind: 'success', text: '✓ data/jogos/catalogo-local.json' },
  { kind: 'output', text: 'Abra o catálogo local nesta página para explorar os resultados.' },
  { kind: 'note', text: '# fim da simulação · nenhum comando foi executado' },
];
const terminal = { running: false, complete: false, line: 0, character: 0, timer: null, current: null };
function setTerminalButton() {
  const button = $('#terminal-play');
  button.innerHTML = terminal.running ? '<span aria-hidden="true">Ⅱ</span> Pausar simulação'
    : terminal.complete ? '<span aria-hidden="true">↻</span> Executar novamente'
      : terminal.line > 0 || terminal.character > 0 ? '<span aria-hidden="true">▶</span> Continuar'
        : '<span aria-hidden="true">▶</span> Executar simulação';
}
function resetTerminal() {
  clearTimeout(terminal.timer);
  Object.assign(terminal, { running: false, complete: false, line: 0, character: 0, timer: null, current: null });
  $('#terminal-output').innerHTML = '<div class="terminal-line note"># acompanhe a coleta, o treino e a exportação</div><div class="terminal-line command"><span class="terminal-cursor" aria-hidden="true"></span></div>';
  $('#terminal-status').textContent = 'Pronto para começar';
  setTerminalButton();
}
function terminalStep() {
  if (!terminal.running) return;
  const output = $('#terminal-output');
  if (terminal.line >= transcript.length) {
    terminal.running = false; terminal.complete = true;
    $('#terminal-status').textContent = 'Simulação concluída'; setTerminalButton(); return;
  }
  const entry = transcript[terminal.line];
  if (!terminal.current) {
    terminal.current = document.createElement('div');
    terminal.current.className = `terminal-line ${entry.kind}`;
    output.append(terminal.current);
  }
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (entry.kind === 'command' && !reduced && terminal.character < entry.text.length) {
    terminal.character += 2;
    terminal.current.textContent = entry.text.slice(0, terminal.character);
    terminal.timer = setTimeout(terminalStep, 26);
  } else {
    terminal.current.textContent = entry.text;
    terminal.line += 1; terminal.character = 0; terminal.current = null;
    $('#terminal-status').textContent = `Etapa ${Math.min(terminal.line, transcript.length)} de ${transcript.length} · simulação`;
    terminal.timer = setTimeout(terminalStep, reduced ? 0 : entry.kind === 'command' ? 440 : 600);
  }
  output.scrollTop = output.scrollHeight;
}
$('#terminal-play').addEventListener('click', () => {
  if (terminal.running) {
    clearTimeout(terminal.timer); terminal.running = false;
    $('#terminal-status').textContent = 'Simulação pausada'; setTerminalButton(); return;
  }
  if (terminal.complete) resetTerminal();
  if (terminal.line === 0 && terminal.character === 0) $('#terminal-output').replaceChildren();
  terminal.running = true; setTerminalButton(); terminalStep();
});
$('#terminal-reset').addEventListener('click', resetTerminal);

renderMode();
renderCatalog();
renderDetail();
resetTerminal();
