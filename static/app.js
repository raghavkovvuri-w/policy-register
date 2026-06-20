// Policy Register Dashboard - Client-side JavaScript

// Register datalabels plugin
Chart.register(ChartDataLabels);

// --- Tab switching ---
function switchTab(id, btn) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  if (btn) btn.classList.add('active');
}

function filterByStatus(status) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-register').classList.add('active');
  document.querySelectorAll('.tab-btn')[0].classList.add('active');
  document.getElementById('statusFilter').value = status;
  filterTable();
}

// --- Table filtering ---
function filterTable() {
  const search = document.getElementById('searchInput').value.toLowerCase();
  const source = document.getElementById('sourceFilter').value;
  const status = document.getElementById('statusFilter').value;
  const category = document.getElementById('categoryFilter').value;
  const rows = document.querySelectorAll('.policy-row');
  rows.forEach(row => {
    const text = row.textContent.toLowerCase();
    const rSource = row.dataset.source;
    const rStatus = row.dataset.status;
    const rCats = row.dataset.categories || '';
    const show = (!search || text.includes(search)) &&
                 (!source || rSource === source) &&
                 (!status || rStatus === status) &&
                 (!category || rCats.includes(category));
    row.style.display = show ? '' : 'none';
    row.nextElementSibling.style.display = 'none';
  });
}

// --- Row expand ---
function toggleDetail(row) {
  const detail = row.nextElementSibling;
  detail.style.display = detail.style.display === 'none' ? '' : 'none';
}

// --- Sort ---
function sortTable(col) {
  const table = document.getElementById('policyTable');
  const tbody = table.querySelector('tbody');
  const pairs = [];
  tbody.querySelectorAll('.policy-row').forEach(r => pairs.push([r, r.nextElementSibling]));
  const dir = table.dataset.sortDir === 'asc' ? 'desc' : 'asc';
  table.dataset.sortDir = dir;
  pairs.sort((a, b) => {
    let av = a[0].cells[col].textContent.trim();
    let bv = b[0].cells[col].textContent.trim();
    return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
  });
  pairs.forEach(([r, d]) => { tbody.appendChild(r); tbody.appendChild(d); });
}

// --- Action tab filtering ---
function filterActions() {
  const source = document.getElementById('actionSourceFilter').value;
  const cat = document.getElementById('actionCatFilter').value;
  document.querySelectorAll('.action-card').forEach(card => {
    const cardSource = card.dataset.source || '';
    const cardCats = card.dataset.categories || '';
    const matchSource = !source || cardSource === source;
    const matchCat = !cat || cardCats.includes(cat);
    card.style.display = (matchSource && matchCat) ? '' : 'none';
  });
}

// --- PDF Modal ---
function openPdf(source, filename) {
  const modal = document.getElementById('pdfModal');
  const frame = document.getElementById('pdfFrame');
  const title = document.getElementById('pdfTitle');
  title.textContent = filename.replace(/^[a-f0-9]+_/, '').replace(/-/g, ' ').replace('.pdf', '');
  frame.src = '/pdf/' + source + '/' + filename;
  modal.style.display = 'flex';
}

function closePdf() {
  document.getElementById('pdfModal').style.display = 'none';
  document.getElementById('pdfFrame').src = '';
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closePdf(); });
document.getElementById('pdfModal').addEventListener('click', e => {
  if (e.target === e.currentTarget) closePdf();
});

// --- Charts ---
function initCharts(data) {
  const total = data.status.overdue + data.status.dueSoon + data.status.current + data.status.noDate;

  // Status — horizontal stacked bar (cleaner than doughnut, no overlap)
  new Chart(document.getElementById('statusChart'), {
    type: 'bar',
    data: {
      labels: ['All Policies'],
      datasets: [
        { label: `Overdue (${data.status.overdue})`, data: [data.status.overdue], backgroundColor: '#E63946', borderRadius: 3 },
        { label: `Due Soon (${data.status.dueSoon})`, data: [data.status.dueSoon], backgroundColor: '#F4A261', borderRadius: 3 },
        { label: `Current (${data.status.current})`, data: [data.status.current], backgroundColor: '#2A9D8F', borderRadius: 3 },
        { label: `No Date (${data.status.noDate})`, data: [data.status.noDate], backgroundColor: '#ADB5BD', borderRadius: 3 }
      ]
    },
    options: {
      responsive: true,
      indexAxis: 'y',
      plugins: {
        legend: { position: 'bottom', labels: { font: { size: 11, family: 'Inter' }, padding: 12, usePointStyle: true } },
        datalabels: {
          color: '#fff',
          font: { weight: 'bold', size: 12 },
          formatter: (value) => {
            const pct = Math.round(value / total * 100);
            return value > 0 ? `${value} (${pct}%)` : '';
          }
        }
      },
      scales: {
        x: { stacked: true, display: false },
        y: { stacked: true, display: false }
      }
    }
  });

  // Category horizontal bar — top 8, sorted, with counts
  const catEntries = Object.entries(data.categories)
    .sort((a, b) => b[1].total - a[1].total)
    .slice(0, 8);
  const catLabels = catEntries.map(([k]) => k.charAt(0).toUpperCase() + k.slice(1));
  const catTotals = catEntries.map(([, v]) => v.total);
  const catOverdue = catEntries.map(([, v]) => v.overdue);

  // Category — stacked by source (IEG navy + UCP teal)
  const catIeg = catEntries.map(([, v]) => v.ieg || 0);
  const catUcp = catEntries.map(([, v]) => v.ucp || 0);
  new Chart(document.getElementById('categoryChart'), {
    type: 'bar',
    data: {
      labels: catLabels,
      datasets: [
        { label: 'IEG', data: catIeg, backgroundColor: '#1B1F3B', borderRadius: 3 },
        { label: 'UCP', data: catUcp, backgroundColor: '#43B9AC', borderRadius: 3 }
      ]
    },
    options: {
      responsive: true,
      indexAxis: 'y',
      plugins: {
        legend: { position: 'bottom', labels: { font: { size: 11, family: 'Inter' }, usePointStyle: true } },
        datalabels: {
          color: '#fff',
          font: { size: 10, weight: 'bold' },
          formatter: (value) => value > 0 ? value : ''
        }
      },
      scales: {
        x: { stacked: true, beginAtZero: true, grid: { color: '#f0f0f0' } },
        y: { stacked: true, grid: { display: false }, ticks: { font: { size: 11 } } }
      }
    }
  });

  // Confidence doughnut
  const confTotal = data.confidence.high + data.confidence.medium + data.confidence.low;
  new Chart(document.getElementById('confidenceChart'), {
    type: 'doughnut',
    data: {
      labels: ['High Confidence', 'Medium', 'Low'],
      datasets: [{
        data: [data.confidence.high, data.confidence.medium, data.confidence.low],
        backgroundColor: ['#E63946', '#F4A261', '#ADB5BD'],
        borderWidth: 3,
        borderColor: '#fff'
      }]
    },
    options: {
      responsive: true,
      cutout: '55%',
      plugins: {
        legend: { position: 'bottom', labels: { font: { size: 11, family: 'Inter' }, padding: 12 } },
        datalabels: {
          color: '#fff',
          font: { weight: 'bold', size: 11 },
          formatter: (value) => {
            const pct = Math.round(value / confTotal * 100);
            return pct > 5 ? `${value}\n(${pct}%)` : '';
          }
        }
      }
    },
    plugins: [{
      id: 'centerText2',
      beforeDraw(chart) {
        const { ctx, width, height } = chart;
        ctx.save();
        ctx.font = 'bold 20px Inter';
        ctx.fillStyle = '#1B1F3B';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(confTotal, width / 2, height / 2 - 6);
        ctx.font = '11px Inter';
        ctx.fillStyle = '#718096';
        ctx.fillText('suggestions', width / 2, height / 2 + 14);
        ctx.restore();
      }
    }]
  });

}

// --- Review Suggestions: Filter policy cards ---
function filterPolicyCards() {
  const source = document.getElementById('reviewSourceFilter').value;
  const cat = document.getElementById('reviewCatFilter').value;
  document.querySelectorAll('.policy-suggestion-card').forEach(card => {
    const cardSource = card.dataset.source || '';
    const cardCats = card.dataset.categories || '';
    const show = (!source || cardSource === source) && (!cat || cardCats.includes(cat));
    card.style.display = show ? '' : 'none';
  });
}

// --- Review Suggestions: Load items on expand ---
let reviewDataCache = null;

document.querySelectorAll('.policy-suggestion-card').forEach((card, idx) => {
  card.addEventListener('toggle', async function() {
    if (!this.open) return;
    const container = this.querySelector('.psc-items');
    if (container.innerHTML.trim()) return; // already loaded

    if (!reviewDataCache) {
      const resp = await fetch('/api/review');
      reviewDataCache = await resp.json();
    }

    const policyName = this.querySelector('.psc-name').textContent;
    const items = reviewDataCache.filter(i => i.policy_name === policyName);

    let html = '';
    items.forEach(item => {
      const confClass = item.confidence === 'high' ? 'conf-high' : item.confidence === 'medium' ? 'conf-medium' : '';
      html += `<div class="review-item ${confClass}">
        <div class="ri-header">
          <span class="ri-cat">${esc(item.category || '')}</span>
          <span class="ri-conf">${item.confidence || 'low'}</span>
        </div>
        <p class="ri-obs">${esc(item.observation || '')}</p>
      </div>`;
    });
    container.innerHTML = html || '<p style="color:#718096;padding:12px;">No items.</p>';
  });
});

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
