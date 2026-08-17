let currentDatasetMaturity = 0;
let priceChartInstance = null;

document.addEventListener('DOMContentLoaded', () => {
    fetchSearchOptions();
    fetchDashboard();
});

function showTab(tabId) {
    document.getElementById('booking-tab').style.display = tabId === 'booking' ? 'block' : 'none';
    document.getElementById('dashboard-tab').style.display = tabId === 'dashboard' ? 'block' : 'none';
    
    document.querySelectorAll('.nav-links span').forEach(el => el.classList.remove('active'));
    event.target.classList.add('active');
    
    if(tabId === 'dashboard') {
        fetchDashboard();
    }
}

async function fetchDashboard() {
    try {
        const res = await fetch('/api/dashboard');
        const data = await res.json();
        
        currentDatasetMaturity = data.dataset_maturity_days || 0;
        updateMaturityIndicator(currentDatasetMaturity);
        
        const html = `
            <div class="stat-card">
                <h3>Collector Status</h3>
                <div class="value">${data.status}</div>
                <div class="status-indicator status-${data.status}">${data.status === 'RUNNING' ? 'Healthy' : 'Check Logs'}</div>
            </div>
            <div class="stat-card">
                <h3>Dataset Maturity</h3>
                <div class="value">${data.dataset_maturity_days} Days</div>
                <div style="font-size:0.8rem; color:#666; margin-top:5px;">Target: 90 Days</div>
            </div>
            <div class="stat-card">
                <h3>Scrapes (Last 24h)</h3>
                <div class="value">${data.scrapes_24h}</div>
            </div>
            <div class="stat-card">
                <h3>Services Collected Today</h3>
                <div class="value">${data.services_today}</div>
            </div>
            <div class="stat-card">
                <h3>Failed Queue</h3>
                <div class="value">${data.failed_queue}</div>
            </div>
        `;
        document.getElementById('dashboard-content').innerHTML = html;
        
    } catch (e) {
        document.getElementById('dashboard-content').innerHTML = `<div style="color:red;">Error loading dashboard</div>`;
    }
}

async function fetchSearchOptions() {
    const res = await fetch('/api/search_options');
    const data = await res.json();
    
    const select = document.getElementById('route-select');
    select.innerHTML = '<option value="">Select a route</option>';
    data.routes.forEach(r => {
        select.innerHTML += `<option value="${r}">${r.replace('-', ' → ')}</option>`;
    });
    
    const dateTabs = document.getElementById('date-tabs');
    dateTabs.innerHTML = '';
    data.dates.forEach((d, index) => {
        const dateObj = new Date(d);
        const dayName = dateObj.toLocaleDateString('en-US', { weekday: 'short' });
        const dayNum = dateObj.getDate();
        const month = dateObj.toLocaleDateString('en-US', { month: 'short' });
        
        const btn = document.createElement('button');
        btn.className = `date-tab ${index === 0 ? 'active' : ''}`;
        btn.dataset.date = d;
        btn.innerHTML = `<strong>${dayNum} ${month}</strong><br>${dayName}`;
        btn.onclick = () => {
            document.querySelectorAll('.date-tab').forEach(el => el.classList.remove('active'));
            btn.classList.add('active');
            searchBuses();
        };
        dateTabs.appendChild(btn);
    });
}

async function searchBuses() {
    const route = document.getElementById('route-select').value;
    const activeDateBtn = document.querySelector('.date-tab.active');
    
    if (!route || !activeDateBtn) return;
    
    const date = activeDateBtn.dataset.date;
    
    document.getElementById('results-section').classList.remove('hidden');
    document.getElementById('bus-list').innerHTML = '<div style="padding:2rem;">Searching buses...</div>';
    
    const res = await fetch(`/api/services?route=${route}&date=${date}`);
    const data = await res.json();
    
    renderBusList(data);
}

function renderBusList(buses) {
    const list = document.getElementById('bus-list');
    list.innerHTML = '';
    
    if (buses.length === 0) {
        list.innerHTML = '<div style="padding:2rem;">No buses found for this date.</div>';
        return;
    }
    
    buses.forEach(b => {
        const card = document.createElement('div');
        card.className = 'bus-card';
        
        const departureTime = b.departure ? b.departure.split(' ')[1] : 'Unknown';
        
        let priceHtml = '';
        if (b.cheapest_seater) priceHtml += `<div>Seater from <strong>₹${Math.round(b.cheapest_seater)}</strong></div>`;
        if (b.cheapest_sleeper) priceHtml += `<div>Sleeper from <strong>₹${Math.round(b.cheapest_sleeper)}</strong></div>`;
        if (!priceHtml) priceHtml = `<div style="color:red;">Sold Out</div>`;
        
        let intelHtml = '';
        if (b.recommendation === "BOOK NOW") {
            intelHtml = `<span style="color:#2e7d32; font-weight:bold; font-size:0.8rem;">✓ Book Now (Lowest Expected)</span>`;
        } else if (b.recommendation.includes("WAIT")) {
            intelHtml = `<span style="color:#f57f17; font-weight:bold; font-size:0.8rem;">⌛ Wait (Price may drop)</span>`;
        } else if (b.recommendation === "INSUFFICIENT DATA") {
            intelHtml = `<span style="color:#9e9e9e; font-size:0.8rem;">Dataset gathering...</span>`;
        }
        
        let histHtml = '';
        if (b.historical_min) {
            histHtml = `<div style="font-size:0.75rem; color:#666; margin-top:4px;">Historical Low: ₹${Math.round(b.historical_min)}</div>`;
        }

        card.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <div>
                    <h3 style="margin-bottom:0.25rem;">${b.operator}</h3>
                    <div style="color:var(--text-light); font-size:0.9rem; margin-bottom:1rem;">${b.bus_type}</div>
                    
                    <div style="display:flex; gap:2rem; align-items:center;">
                        <div>
                            <div style="font-size:0.8rem; color:var(--text-light);">Departure</div>
                            <div style="font-size:1.2rem; font-weight:700;">${departureTime}</div>
                        </div>
                        <div>
                            <div style="font-size:0.8rem; color:var(--text-light);">Availability</div>
                            <div style="font-size:1.2rem; font-weight:700; color:${b.available_seats > 5 ? 'var(--primary)' : '#d32f2f'}">${b.available_seats} <span style="font-size:0.8rem; font-weight:400;">/ ${b.total_seats}</span></div>
                        </div>
                    </div>
                </div>
                
                <div style="text-align:right;">
                    <div style="margin-bottom:1rem;">
                        ${priceHtml}
                        ${histHtml}
                        ${intelHtml}
                    </div>
                    <button class="btn" onclick="openSeatMap(${b.service_id}, '${b.operator}')">View Seats</button>
                </div>
            </div>
        `;
        
        list.appendChild(card);
    });
}

function updateMaturityIndicator(days) {
    const text = document.getElementById('maturity-text');
    let status = '';
    if (days >= 90) status = 'Mature (90+ Days)';
    else if (days >= 60) status = 'High Confidence';
    else if (days >= 30) status = 'Medium Confidence';
    else if (days >= 7) status = 'Low Confidence';
    else status = 'Insufficient Data';
    
    text.innerText = `Dataset Maturity: ${days}/90 Days (${status})`;
}

async function openSeatMap(serviceId, operatorName) {
    document.getElementById('seatmap-modal').classList.add('active');
    document.getElementById('seatmap-header').innerText = `Select Seat - ${operatorName}`;
    document.getElementById('intelligence-panel').classList.add('hidden');
    document.getElementById('intel-placeholder').style.display = 'block';
    
    document.getElementById('bus-layout-lower').innerHTML = '<div class="bus-front"></div><div style="padding:2rem;">Loading layout...</div>';
    document.getElementById('bus-layout-upper').innerHTML = '<div class="bus-front"></div>';
    
    const res = await fetch(`/api/seatmap/${serviceId}`);
    const data = await res.json();
    
    renderPhysicalGrid(data.seats, serviceId);
}

function closeSeatMap() {
    document.getElementById('seatmap-modal').classList.remove('active');
}

function switchDeck(deck) {
    document.querySelectorAll('.deck-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`btn-${deck.toLowerCase()}`).classList.add('active');
    
    if (deck === 'Lower') {
        document.getElementById('bus-layout-lower').classList.remove('hidden');
        document.getElementById('bus-layout-upper').classList.add('hidden');
    } else {
        document.getElementById('bus-layout-lower').classList.add('hidden');
        document.getElementById('bus-layout-upper').classList.remove('hidden');
    }
}

function renderPhysicalGrid(seats, serviceId) {
    const lowerSeats = seats.filter(s => s.deck === 'Lower');
    const upperSeats = seats.filter(s => s.deck === 'Upper');
    
    if (upperSeats.length === 0) {
        document.getElementById('deck-selector').style.display = 'none';
    } else {
        document.getElementById('deck-selector').style.display = 'flex';
    }
    switchDeck('Lower');
    
    let cheapestAvailable = null;
    let minFare = Infinity;
    seats.forEach(s => {
        if (s.available) {
            const f = s.discounted_fare || s.seat_fare;
            if (f < minFare) {
                minFare = f;
                cheapestAvailable = s.seat_number;
            }
        }
    });
    
    renderDeck(lowerSeats, 'bus-layout-lower', cheapestAvailable, serviceId);
    renderDeck(upperSeats, 'bus-layout-upper', cheapestAvailable, serviceId);
}

function renderDeck(deckSeats, containerId, cheapestSeat, serviceId) {
    const container = document.getElementById(containerId);
    container.innerHTML = '<div class="bus-front"></div>';
    if (deckSeats.length === 0) return;
    
    let maxRow = 0;
    deckSeats.forEach(s => {
        const r = parseInt(s.row_id) || 1;
        if (r > maxRow) maxRow = r;
    });
    
    // We don't strictly need maxCol if we use explicit grid-column lines, but we set explicit columns to be safe
    let maxCol = 0;
    deckSeats.forEach(s => {
        const c = parseInt(s.column_id) || 1;
        const span = parseInt(s.col_span) || 1;
        if (c + span - 1 > maxCol) maxCol = c + span - 1;
    });
    
    container.style.gridTemplateColumns = `repeat(${maxCol}, 40px)`;
    container.style.gridTemplateRows = `repeat(${maxRow}, 40px)`;
    container.style.justifyContent = 'center';
    
    deckSeats.forEach(s => {
        const r = parseInt(s.row_id) || 1;
        const c = parseInt(s.column_id) || 1;
        const span = parseInt(s.col_span) || 1;
        
        const div = document.createElement('div');
        div.className = 'seat';
        div.style.gridRow = r;
        
        const isSleeper = s.seat_type !== 'SS';
        if (!isSleeper) {
            div.classList.add('seater');
            div.style.gridColumn = c;
        } else {
            div.classList.add('sleeper');
            div.style.gridColumn = span > 1 ? `${c} / span ${span}` : c;
        }
        
        if (!s.available) div.classList.add('sold');
        else if (s.ladies_seat) div.classList.add('ladies');
        
        if (s.seat_number === cheapestSeat) div.classList.add('cheapest');
        
        let html = `<div class="seat-no">${s.seat_number}</div>`;
        if (s.available) {
            const f = s.discounted_fare || s.seat_fare;
            if (f) html += `<div class="seat-price">₹${Math.round(f)}</div>`;
        } else {
            html += `<div class="seat-price" style="font-size:0.55rem;">SOLD</div>`;
        }
        
        if (isSleeper) {
            html += `<div class="pillow"></div>`;
        }
        
        div.innerHTML = html;
        
        if (s.available) {
            div.onclick = () => {
                document.querySelectorAll('.seat').forEach(el => el.classList.remove('selected'));
                div.classList.add('selected');
                fetchIntelligence(serviceId, s.seat_number);
            };
        }
        
        container.appendChild(div);
    });
}

async function fetchIntelligence(serviceId, seatNo) {
    document.getElementById('intel-placeholder').style.display = 'none';
    const panel = document.getElementById('intelligence-panel');
    panel.classList.remove('hidden');
    
    document.getElementById('intel-seat-no').innerText = seatNo;
    document.getElementById('intel-current-fare').innerText = 'Loading...';
    document.getElementById('intel-hist-min').innerText = '-';
    document.getElementById('intel-prob').innerText = '-';
    document.getElementById('intel-window').innerText = '-';
    document.getElementById('intel-confidence').innerText = '-';
    document.getElementById('intel-reason').innerText = '';
    document.getElementById('intel-recommendation-box').innerHTML = '';
    
    if (priceChartInstance) {
        priceChartInstance.destroy();
        priceChartInstance = null;
    }
    
    const res = await fetch(`/api/intelligence?service_id=${serviceId}&seat_number=${seatNo}`);
    const data = await res.json();
    
    if (data.status === "INSUFFICIENT_DATA") {
        document.getElementById('intel-current-fare').innerText = 'Unknown';
        document.getElementById('intel-recommendation-box').innerHTML = `<span style="color:#9e9e9e;">Insufficient Data</span>`;
        document.getElementById('intel-reason').innerText = data.message;
        return;
    }
    
    document.getElementById('intel-current-fare').innerText = `₹${Math.round(data.current_fare)}`;
    document.getElementById('intel-hist-min').innerText = data.historical_minimum ? `₹${Math.round(data.historical_minimum)}` : 'N/A';
    document.getElementById('intel-prob').innerText = `${Math.round(data.price_drop_probability)}%`;
    document.getElementById('intel-window').innerText = data.best_booking_window;
    
    const conf = data.confidence;
    let confColor = '#333';
    if(conf === 'HIGH') confColor = '#2e7d32';
    if(conf === 'MEDIUM') confColor = '#f57f17';
    if(conf === 'LOW' || conf === 'INSUFFICIENT DATA') confColor = '#d32f2f';
    document.getElementById('intel-confidence').innerHTML = `<span style="color:${confColor}; font-weight:bold;">${conf}</span>`;
    
    const recBox = document.getElementById('intel-recommendation-box');
    if (data.recommendation === "BOOK NOW") {
        recBox.innerHTML = `<div style="background:#e8f5e9; color:#2e7d32; padding:8px 16px; border-radius:8px; font-weight:bold; font-size:1.1rem; border:2px solid #a5d6a7;">✓ BOOK NOW</div>`;
    } else if (data.recommendation.includes("WAIT")) {
        recBox.innerHTML = `<div style="background:#fff3e0; color:#ef6c00; padding:8px 16px; border-radius:8px; font-weight:bold; font-size:1.1rem; border:2px solid #ffcc80;">⌛ WAIT</div>`;
    } else {
        recBox.innerHTML = `<div style="background:#f5f5f5; color:#757575; padding:8px 16px; border-radius:8px; font-weight:bold; font-size:1.1rem; border:2px solid #e0e0e0;">NOT ENOUGH DATA</div>`;
    }
    
    document.getElementById('intel-reason').innerText = data.why_reason;
    
    renderChart(data.chart_data, data.current_fare, data.expected_lowest_fare);
}

function renderChart(historyData, currentFare, expectedMin) {
    if(!historyData || historyData.length === 0) return;
    
    const ctx = document.getElementById('priceChart').getContext('2d');
    
    // Sort by hours_to_departure descending (from furthest away to closest to departure)
    historyData.sort((a,b) => b.htd - a.htd);
    
    const labels = historyData.map(d => `${Math.round(d.htd)}h`);
    const dataPoints = historyData.map(d => d.fare);
    
    const expectedLine = new Array(historyData.length).fill(expectedMin);
    
    priceChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Observed Fare',
                    data: dataPoints,
                    borderColor: '#1e88e5',
                    backgroundColor: 'rgba(30, 136, 229, 0.1)',
                    borderWidth: 2,
                    pointRadius: 4,
                    fill: true,
                    tension: 0.2
                },
                {
                    label: 'Expected Minimum',
                    data: expectedLine,
                    borderColor: '#f57f17',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    pointRadius: 0,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { boxWidth: 12, font: { size: 10 } }
                }
            },
            scales: {
                x: {
                    title: { display: true, text: 'Hours Before Departure', font: { size: 10 } },
                    reverse: true // Left is high hours (far away), right is 0 hours (now)
                },
                y: {
                    title: { display: true, text: 'Fare (₹)', font: { size: 10 } },
                    suggestedMin: expectedMin ? expectedMin * 0.9 : undefined
                }
            }
        }
    });
}
