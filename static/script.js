let currentIntelligentSeats = [];
let currentBuses = [];
let selectedDate = '';

async function loadSearchOptions() {
    try {
        const response = await fetch('/api/search_options');
        const data = await response.json();
        
        const routeSelect = document.getElementById('route-select');
        routeSelect.innerHTML = '';
        data.routes.forEach(r => {
            const opt = document.createElement('option');
            opt.value = r;
            opt.innerText = r;
            routeSelect.appendChild(opt);
        });
        
        const calTabs = document.getElementById('calendar-tabs');
        calTabs.innerHTML = '';
        
        let availableDates = data.dates;
        // Limit to 7 days max for rolling 7-day window
        if (availableDates.length > 7) {
            availableDates = availableDates.slice(0, 7);
        }
        
        if (availableDates.length > 0) {
            availableDates.forEach((d, idx) => {
                const dateObj = new Date(d);
                const dayName = dateObj.toLocaleDateString('en-US', { weekday: 'short' });
                const dayNum = dateObj.toLocaleDateString('en-US', { day: 'numeric', month: 'short' });
                
                const tab = document.createElement('div');
                tab.className = 'cal-tab';
                if (idx === 0) {
                    tab.classList.add('active');
                    selectedDate = d;
                }
                
                tab.innerHTML = `
                    <div class="cal-day">${dayName}</div>
                    <div class="cal-date">${dayNum.split(' ')[1]}</div>
                `;
                
                tab.onclick = () => {
                    document.querySelectorAll('.cal-tab').forEach(t => t.classList.remove('active'));
                    tab.classList.add('active');
                    selectedDate = d;
                    // Auto search when date changes
                    if (document.getElementById('route-select').value) {
                        searchBuses();
                    }
                };
                
                calTabs.appendChild(tab);
            });
            
            // Auto trigger initial search
            searchBuses();
        } else {
            calTabs.innerHTML = '<div style="color: var(--text-secondary); padding: 0.5rem 0;">No dates available</div>';
        }
    } catch (e) {
        console.error("Error loading search options:", e);
    }
}


async function searchBuses() {
    const route = document.getElementById('route-select').value;
    if (!route || !selectedDate) return;
    
    const busList = document.getElementById('bus-list');
    busList.innerHTML = 'Loading buses...';
    document.getElementById('results-section').style.display = 'block';
    
    try {
        const response = await fetch(`/api/services?route=${encodeURIComponent(route)}&date=${selectedDate}`);
        currentBuses = await response.json();
        renderBuses();
    } catch (e) {
        busList.innerHTML = 'Error searching buses.';
        console.error(e);
    }
}

// Add event listeners for filters
document.querySelectorAll('.op-filter, .type-filter').forEach(el => {
    el.addEventListener('change', renderBuses);
});

function renderBuses() {
    const busList = document.getElementById('bus-list');
    busList.innerHTML = '';
    
    if (!currentBuses || currentBuses.length === 0) {
        busList.innerHTML = 'No tracked buses found for this route and date.';
        return;
    }

    // 1. Get active filters
    const activeOps = Array.from(document.querySelectorAll('.op-filter:checked')).map(cb => cb.value.toLowerCase());
    const activeTypes = Array.from(document.querySelectorAll('.type-filter:checked')).map(cb => cb.value.toLowerCase());
    const sortVal = document.getElementById('sort-select').value;

    // 2. Filter logic
    let filtered = currentBuses.filter(b => {
        const opMatch = activeOps.some(op => b.operator.toLowerCase().includes(op));
        
        const bTypeLower = b.bus_type.toLowerCase();
        let typeMatch = false;
        if (activeTypes.includes('seater') && bTypeLower.includes('seater')) typeMatch = true;
        if (activeTypes.includes('sleeper') && bTypeLower.includes('sleeper')) typeMatch = true;
        
        return opMatch && typeMatch;
    });

    // 3. Sorting logic
    filtered.sort((a, b) => {
        const timeA = new Date(a.departure).getTime();
        const timeB = new Date(b.departure).getTime();
        const priceA = a.cheapest_seater || a.cheapest_sleeper || 99999;
        const priceB = b.cheapest_seater || b.cheapest_sleeper || 99999;
        
        if (sortVal === 'time_early') return timeA - timeB;
        if (sortVal === 'time_late') return timeB - timeA;
        if (sortVal === 'price_low') return priceA - priceB;
        if (sortVal === 'price_high') return priceB - priceA;
        if (sortVal === 'seats_high') return b.available_seats - a.available_seats;
        return 0;
    });

    if (filtered.length === 0) {
        busList.innerHTML = 'No buses match your filter criteria.';
        return;
    }

    // 4. Render
    filtered.forEach(b => {
        const card = document.createElement('div');
        card.className = 'bus-card';
        
        const depTime = b.departure.split(' ')[1] || b.departure;
        
        card.innerHTML = `
            <div class="bus-info-main">
                <div class="bus-time">${depTime}</div>
                <div>
                    <div class="bus-operator">${b.operator}</div>
                    <div class="bus-type">${b.bus_type}</div>
                </div>
            </div>
            <div class="bus-fares">
                ${b.cheapest_seater ? `<div class="fare-item"><span class="fare-label">Seater</span><span class="fare-val">₹${b.cheapest_seater}</span></div>` : ''}
                ${b.cheapest_sleeper ? `<div class="fare-item"><span class="fare-label">Sleeper</span><span class="fare-val">₹${b.cheapest_sleeper}</span></div>` : ''}
                <div style="margin-left: 2rem; text-align: center;">
                    <div style="font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 0.5rem;">${b.available_seats} / ${b.total_seats} seats</div>
                    <button class="view-seats-btn" onclick="openSeatMap(${b.service_id})">VIEW SEATS</button>
                </div>
            </div>
        `;
        busList.appendChild(card);
    });
}

async function openSeatMap(serviceId) {
    document.getElementById('seatmap-modal').style.display = 'flex';
    document.getElementById('seatmap-grid').innerHTML = '<div class="intel-placeholder"><div class="cal-skeleton" style="width:100%; height:150px; margin-bottom:1rem;"></div><div class="cal-skeleton" style="width:100%; height:150px;"></div></div>';
    document.getElementById('intelligence-panel').innerHTML = '<div class="intel-placeholder"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity: 0.5; margin-bottom: 1rem;"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg><p>Select an available seat on the layout to view AI price predictions and recommendations.</p></div>';
    
    try {
        const response = await fetch(`/api/seatmap_intelligent?service_id=${serviceId}`);
        const data = await response.json();
        
        if (data.error) {
            document.getElementById('seatmap-grid').innerHTML = data.error;
            return;
        }
        
        currentIntelligentSeats = data.seats;
        
        const depTime = data.service.departure.split(' ')[1] || data.service.departure;
        document.getElementById('seatmap-header').innerText = `${data.service.operator} • ${data.service.route} • ${depTime}`;
        
        const seats = data.seats;
        
        // Fix missing decks
        seats.forEach(s => {
            if (!s.deck || s.deck === 'null') {
                if (s.seat_number.startsWith('U')) s.deck = 'Upper';
                else if (s.seat_number.startsWith('L')) s.deck = 'Lower';
                else s.deck = 'Lower';
            }
        });
        
        const decks = [...new Set(seats.map(s => s.deck))].sort();
        
        let html = '';
         const renderSeat = (seat) => {
            if (!seat) return ''; // no more empty seats needed
            
            let isSleeper = seat.seat_type === 'LB' || seat.seat_type === 'UB';
            let sClass = 'seat-box ';
            if (isSleeper) sClass += 'sleeper ';
            
            if (!seat.available) sClass += 'seat-sold';
            else if (seat.ladies_seat) sClass += 'seat-ladies';
            else sClass += 'seat-available';
            
            let fareHtml = '';
            let recHtml = '';
            if (seat.available) {
                fareHtml = `<div class="s-fare">₹${seat.discounted_fare}</div>`;
                if (seat.intel && seat.intel.recommendation) {
                    const isBook = seat.intel.recommendation.includes("BOOK");
                    const recColor = isBook ? 'var(--accent-green)' : 'var(--accent-yellow)';
                    const recText = isBook ? 'BOOK' : 'WAIT';
                    recHtml = `<div class="s-rec" style="color: ${recColor}">${recText}</div>`;
                }
            }
            
            const onClick = (seat.available && !seat.ladies_seat) ? `onclick="showIntel('${seat.seat_number}')"` : '';
            
            // Explicit CSS Grid Positioning!
            let gridStyle = '';
            if (seat.row_id !== null && seat.column_id !== null) {
                gridStyle = `grid-row: ${seat.row_id}; grid-column: ${seat.column_id}`;
                if (isSleeper) {
                    gridStyle += ' / span 2';
                }
                gridStyle += ';';
            }
            
            return `<div class="${sClass}" style="${gridStyle}" ${onClick} id="seat-UI-${seat.seat_number}">
                <div class="s-num">${seat.seat_number}</div>
                ${fareHtml}
                ${recHtml}
            </div>`;
        };

        const synthesizeGrid = (deckSeats) => {
            deckSeats.sort((a, b) => {
                const numA = parseInt(a.seat_number.replace(/\D/g, '')) || 0;
                const numB = parseInt(b.seat_number.replace(/\D/g, '')) || 0;
                return numA - numB;
            });
            
            deckSeats.forEach((seat, idx) => {
                const pos = idx % 3; 
                seat.column_id = pos === 2 ? 3 : pos; 
                seat.row_id = Math.floor(idx / 3) + 1;
            });
        };

        decks.forEach(deck => {
            let deckSeats = seats.filter(s => s.deck === deck);
            
            const hasCoords = deckSeats.some(s => s.row_id !== null && s.column_id !== null);
            if (!hasCoords) {
                synthesizeGrid(deckSeats);
            }
            
            const maxCol = Math.max(...deckSeats.map(s => s.column_id || 0)); 
            const maxRow = Math.max(...deckSeats.map(s => s.row_id || 0));
            
            html += `<div class="deck-wrapper">
                        <div class="deck-title">${deck}</div>
                        <div class="seat-grid" style="grid-template-columns: repeat(${maxCol}, 40px); grid-template-rows: repeat(${maxRow}, 40px); gap: 8px;">`;
            
            // Render directly into CSS Grid
            deckSeats.forEach(seat => {
                html += renderSeat(seat);
            });
            
            html += `</div></div>`;
        });
        
        document.getElementById('seatmap-grid').innerHTML = html;
        
    } catch(e) {
        document.getElementById('seatmap-grid').innerHTML = 'Error loading seat map.';
        console.error(e);
    }
}

function closeSeatMap() {
    document.getElementById('seatmap-modal').style.display = 'none';
}

function showIntel(seatNumber) {
    // Clear previous selection
    document.querySelectorAll('.seat-box').forEach(el => el.classList.remove('selected'));
    document.getElementById(`seat-UI-${seatNumber}`).classList.add('selected');
    
    const seat = currentIntelligentSeats.find(s => s.seat_number === seatNumber);
    if (!seat || !seat.intel) return;
    
    const intel = seat.intel;
    const isBook = intel.recommendation.includes("BOOK");
    const recClass = isBook ? 'rec-BOOK' : 'rec-WAIT';
    
    let probText = intel.probability_of_price_drop.toFixed(0) + '%';
    if (intel.data_confidence === 'LOW') probText = '—%';
    
    let confClass = 'conf-HIGH';
    if (intel.data_confidence === 'LOW') confClass = 'conf-LOW';
    if (intel.data_confidence === 'MEDIUM') confClass = 'conf-MED';
    
    const expectedSaving = Math.max(0, seat.discounted_fare - intel.expected_minimum);
    
    // Clear previous selected seat
    document.querySelectorAll('.seat-box').forEach(el => el.classList.remove('selected'));
    const seatEl = document.getElementById(`seat-UI-${seatNumber}`);
    if (seatEl) seatEl.classList.add('selected');
    
    const html = `
        <h3 class="gradient-text" style="margin-bottom: 1.5rem; font-size: 1.4rem;">
            Seat ${seatNumber}
            <span style="font-size: 0.9rem; color: var(--text-secondary); font-weight: 500; float: right; margin-top: 0.4rem;">
                ${intel.scrapes_analyzed} data points
            </span>
        </h3>
        
        <div class="intel-row">
            <span class="intel-label">Current Fare</span>
            <span class="intel-val">₹${seat.discounted_fare}</span>
        </div>
        <div class="intel-row">
            <span class="intel-label">Expected Min Fare</span>
            <span class="intel-val">₹${intel.expected_minimum.toFixed(0)}</span>
        </div>
        <div class="intel-row">
            <span class="intel-label">Potential Savings</span>
            <span class="intel-val green">₹${expectedSaving.toFixed(0)}</span>
        </div>
        <div class="intel-row">
            <span class="intel-label">Drop Prob</span>
            <span class="intel-val" title="${intel.data_confidence === 'LOW' ? 'Insufficient evidence' : ''}">${probText}</span>
        </div>
        <div class="intel-row">
            <span class="intel-label">Confidence</span>
            <span class="conf-badge ${confClass}">${intel.data_confidence} (${intel.comparable_journeys} journeys)</span>
        </div>
        <div class="intel-row" style="flex-direction: column; border-bottom: none;">
            <span class="intel-label" style="margin-bottom: 0.5rem;">Best Historical Window</span>
            <span class="intel-val" style="font-size: 0.9rem;">${intel.historical_low_window}</span>
        </div>
        
        <div class="rec-banner ${recClass}">
            ${intel.recommendation}
        </div>
        
        <div style="margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid rgba(255,255,255,0.05); font-size: 0.85rem; color: var(--text-secondary); line-height: 1.5;">
            <strong>Why?</strong><br>
            ${intel.why_reason}
        </div>
    `;
    
    document.getElementById('intelligence-panel').innerHTML = html;
}

// Load options on boot
loadSearchOptions();
