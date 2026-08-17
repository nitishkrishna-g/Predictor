let currentIntelligentSeats = [];
let currentBuses = [];
let selectedDate = '';
let currentServiceId = null;
let currentDeck = 'Lower';

document.addEventListener("DOMContentLoaded", () => {
    loadSearchOptions();
    fetchHealth();
});

async function fetchHealth() {
    try {
        const res = await fetch('/api/health');
        const data = await res.json();
        const mat = document.getElementById('maturity-text');
        if (data.dataset_maturity_days) {
            mat.innerText = `Prediction Dataset: ${data.dataset_maturity_days} / 90 days`;
        }
    } catch (e) {
        console.error("Health check failed", e);
    }
}

async function loadSearchOptions() {
    try {
        const response = await fetch('/api/search_options');
        const data = await response.json();
        
        const routeSelect = document.getElementById('route-select');
        routeSelect.innerHTML = '<option value="">Select a route...</option>';
        data.routes.forEach(r => {
            const opt = document.createElement('option');
            opt.value = r;
            opt.innerText = r;
            routeSelect.appendChild(opt);
        });
        
        const calTabs = document.getElementById('date-tabs');
        calTabs.innerHTML = '';
        
        let availableDates = data.dates;
        
        if (availableDates.length > 0) {
            availableDates.forEach((d, idx) => {
                const dateObj = new Date(d);
                const dayName = dateObj.toLocaleDateString('en-US', { weekday: 'short' });
                const dayNum = dateObj.toLocaleDateString('en-US', { day: 'numeric', month: 'short' });
                
                const tab = document.createElement('div');
                tab.className = 'date-tab';
                if (idx === 0) {
                    tab.classList.add('active');
                    selectedDate = d;
                }
                
                tab.innerHTML = `
                    <span class="day">${dayName}</span>
                    <span class="date">${dayNum.split(' ')[1]}</span>
                `;
                
                tab.onclick = () => {
                    document.querySelectorAll('.date-tab').forEach(t => t.classList.remove('active'));
                    tab.classList.add('active');
                    selectedDate = d;
                    if (document.getElementById('route-select').value) {
                        searchBuses();
                    }
                };
                
                calTabs.appendChild(tab);
            });
        }
    } catch (e) {
        console.error("Error loading search options:", e);
    }
}

async function searchBuses() {
    const route = document.getElementById('route-select').value;
    if (!route || !selectedDate) return;
    
    const busList = document.getElementById('bus-list');
    busList.innerHTML = '<div style="padding:2rem;text-align:center;">Loading intelligent tracking data...</div>';
    document.getElementById('results-section').classList.remove('hidden');
    
    try {
        const response = await fetch(`/api/services?route=${encodeURIComponent(route)}&date=${selectedDate}`);
        currentBuses = await response.json();
        renderBuses();
    } catch (e) {
        busList.innerHTML = '<div style="color:red;padding:2rem;">Error searching buses. Ensure the API is running.</div>';
        console.error(e);
    }
}

function renderBuses() {
    const busList = document.getElementById('bus-list');
    busList.innerHTML = '';
    
    if (!currentBuses || currentBuses.length === 0) {
        busList.innerHTML = '<div style="padding:2rem;text-align:center;">No buses found for this date. The collector may still be gathering data.</div>';
        return;
    }

    currentBuses.forEach(b => {
        const card = document.createElement('div');
        card.className = 'bus-card';
        
        const depTime = b.departure.split(' ')[1] || b.departure;
        
        let priceHtml = '';
        if (b.cheapest_seater) priceHtml += `<div class="price-val">₹${Math.round(b.cheapest_seater)} <span class="price-label">(Seater)</span></div>`;
        if (b.cheapest_sleeper) priceHtml += `<div class="price-val">₹${Math.round(b.cheapest_sleeper)} <span class="price-label">(Sleeper)</span></div>`;
        
        card.innerHTML = `
            <div class="bus-info">
                <div class="operator-name">${b.operator.toUpperCase()}</div>
                <div class="bus-type">${b.bus_type}</div>
                <div style="margin-top:0.5rem; color:var(--text-light); font-size:0.85rem;">
                    Service: ${b.service_key} | Seats: ${b.available_seats}/${b.total_seats}
                </div>
            </div>
            <div class="bus-time">
                ${depTime}
            </div>
            <div class="bus-price">
                ${priceHtml}
                <button class="view-seats-btn" onclick="openSeatMap(${b.service_id})">Select Seats</button>
            </div>
        `;
        busList.appendChild(card);
    });
}

let seatData = {};

async function openSeatMap(serviceId) {
    currentServiceId = serviceId;
    document.getElementById('seatmap-modal').classList.add('active');
    document.getElementById('seatmap-header').innerText = "Loading physical seat layout...";
    document.getElementById('bus-layout-lower').innerHTML = '<div class="bus-front"></div>';
    document.getElementById('bus-layout-upper').innerHTML = '';
    
    // Reset intel panel
    document.getElementById('intelligence-panel').classList.add('hidden');
    document.getElementById('intel-placeholder').classList.remove('hidden');
    
    try {
        const res = await fetch(`/api/seatmap/${serviceId}`);
        const data = await res.json();
        
        if (data.error) {
            document.getElementById('seatmap-header').innerText = "Error: " + data.error;
            return;
        }
        
        document.getElementById('seatmap-header').innerText = `${data.service.operator.toUpperCase()} - ${data.service.departure}`;
        seatData = data;
        
        renderPhysicalSeatMap();
        
    } catch(e) {
        document.getElementById('seatmap-header').innerText = "Failed to load layout.";
        console.error(e);
    }
}

function closeSeatMap() {
    document.getElementById('seatmap-modal').classList.remove('active');
}

function switchDeck(deck) {
    currentDeck = deck;
    document.getElementById('btn-lower').classList.toggle('active', deck === 'Lower');
    document.getElementById('btn-upper').classList.toggle('active', deck === 'Upper');
    
    if (deck === 'Lower') {
        document.getElementById('bus-layout-lower').classList.remove('hidden');
        document.getElementById('bus-layout-upper').classList.add('hidden');
    } else {
        document.getElementById('bus-layout-lower').classList.add('hidden');
        document.getElementById('bus-layout-upper').classList.remove('hidden');
    }
}

function renderPhysicalSeatMap() {
    const lowerContainer = document.getElementById('bus-layout-lower');
    const upperContainer = document.getElementById('bus-layout-upper');
    
    lowerContainer.innerHTML = '<div class="bus-front"></div>';
    upperContainer.innerHTML = '';
    
    let hasUpper = false;
    let minFare = 999999;
    let cheapestSeat = null;

    // First pass: find max dimensions and cheapest available seat
    seatData.seats.forEach(s => {
        if (s.deck === 'Upper') hasUpper = true;
        
        if (s.available && !s.ladies_seat) {
            let fare = s.discounted_fare || s.seat_fare;
            if (fare && fare < minFare) {
                minFare = fare;
                cheapestSeat = s.seat_number;
            }
        }
    });
    
    if (!hasUpper) {
        document.getElementById('deck-selector').classList.add('hidden');
        switchDeck('Lower');
    } else {
        document.getElementById('deck-selector').classList.remove('hidden');
    }

    // Function to render a specific deck
    function renderDeck(deckName, container) {
        let deckSeats = seatData.seats.filter(s => s.deck === deckName);
        if (deckSeats.length === 0) return;
        
        let maxRow = Math.max(...deckSeats.map(s => parseInt(s.row_id) || 1));
        let maxCol = Math.max(...deckSeats.map(s => parseInt(s.column_id) || 1));
        
        // CSS Grid setup: columns are X-axis (length of bus), rows are Y-axis (width of bus)
        // Usually AbhiBus sets column=1 at the front, row=1 at the left window.
        container.style.gridTemplateColumns = `repeat(${maxCol}, 40px)`;
        container.style.gridTemplateRows = `repeat(${maxRow}, 40px)`;
        container.style.justifyContent = 'center';
        
        deckSeats.forEach(s => {
            const r = parseInt(s.row_id) || 1;
            const c = parseInt(s.column_id) || 1;
            
            const div = document.createElement('div');
            div.className = 'seat';
            div.style.gridRow = r;
            
            // Seat style classes
            const isSleeper = s.seat_type !== 'SS';
            if (!isSleeper) {
                div.classList.add('seater');
                div.style.gridColumn = c;
            } else {
                div.classList.add('sleeper');
                // Check if this sleeper needs to span 2 columns to match the grid
                // If maxCol > 5 and this is a sleeper, it likely spans 2 columns in AbhiBus logic
                if (maxCol >= 5) {
                    div.style.gridColumn = `${c} / span 2`;
                } else {
                    div.style.gridColumn = c;
                }
            }
            
            if (!s.available) div.classList.add('sold');
            else if (s.ladies_seat) div.classList.add('ladies');
            
            if (s.seat_number === cheapestSeat) div.classList.add('cheapest');
            
            // Text
            let html = `<div class="seat-no">${s.seat_number}</div>`;
            if (s.available) {
                const f = s.discounted_fare || s.seat_fare;
                if (f) html += `<div class="seat-price">₹${Math.round(f)}</div>`;
            } else {
                html += `<div class="seat-price" style="font-size:0.55rem;">SOLD</div>`;
            }
            
            // For sleepers, add a small pillow visual cue
            if (isSleeper) {
                html += `<div class="pillow"></div>`;
            }
            
            div.innerHTML = html;
            
            if (s.available) {
                div.onclick = () => {
                    document.querySelectorAll('.seat').forEach(el => el.classList.remove('selected'));
                    div.classList.add('selected');
                    fetchIntelligence(s.seat_number);
                };
            }
            
            container.appendChild(div);
        });
    }
    
    renderDeck('Lower', lowerContainer);
    renderDeck('Upper', upperContainer);
}

async function fetchIntelligence(seatNo) {
    document.getElementById('intel-placeholder').classList.add('hidden');
    const panel = document.getElementById('intelligence-panel');
    panel.classList.remove('hidden');
    
    document.getElementById('intel-seat-no').innerText = seatNo;
    document.getElementById('intel-current-fare').innerText = "Loading AI Intelligence...";
    document.getElementById('intel-hist-min').innerText = "...";
    document.getElementById('intel-prob').innerText = "...";
    document.getElementById('intel-window').innerText = "...";
    document.getElementById('intel-confidence').innerText = "...";
    document.getElementById('intel-reason').innerText = "";
    document.getElementById('intel-recommendation-box').className = "rec-badge rec-none";
    document.getElementById('intel-recommendation-box').innerText = "Analyzing historical curve...";
    
    try {
        const res = await fetch(`/api/intelligence?service_id=${currentServiceId}&seat_number=${seatNo}`);
        const intel = await res.json();
        
        if (intel.status === "INSUFFICIENT_DATA") {
            document.getElementById('intel-current-fare').innerText = "Not available";
            document.getElementById('intel-recommendation-box').innerText = "INSUFFICIENT DATA";
            document.getElementById('intel-reason').innerText = intel.message || "We need more days of historical data for this route before we can generate trustworthy predictions.";
            return;
        }
        
        if (intel.error) throw new Error(intel.error);
        
        document.getElementById('intel-current-fare').innerText = `₹${Math.round(intel.current_fare)}`;
        
        if (intel.historical_minimum) {
            document.getElementById('intel-hist-min').innerText = `₹${Math.round(intel.historical_minimum)}`;
        } else {
            document.getElementById('intel-hist-min').innerText = "N/A";
        }
        
        if (intel.price_drop_probability !== undefined) {
            document.getElementById('intel-prob').innerText = `${Math.round(intel.price_drop_probability * 100)}%`;
        }
        
        document.getElementById('intel-window').innerText = intel.best_booking_window || "Unknown";
        
        const confEl = document.getElementById('intel-confidence');
        confEl.innerText = intel.confidence.toUpperCase();
        confEl.className = "intel-value";
        if (intel.confidence === 'high') confEl.classList.add('conf-high');
        else if (intel.confidence === 'medium') confEl.classList.add('conf-med');
        else if (intel.confidence === 'low') confEl.classList.add('conf-low');
        else confEl.classList.add('conf-none');
        
        const recBox = document.getElementById('intel-recommendation-box');
        recBox.innerText = intel.recommendation.toUpperCase();
        recBox.className = "rec-badge";
        if (intel.recommendation === 'book') recBox.classList.add('rec-book');
        else if (intel.recommendation === 'wait') recBox.classList.add('rec-wait');
        else recBox.classList.add('rec-none');
        
        document.getElementById('intel-reason').innerText = intel.why_reason || "";
        
    } catch (e) {
        console.error(e);
        document.getElementById('intel-current-fare').innerText = "Error loading intelligence";
    }
}
