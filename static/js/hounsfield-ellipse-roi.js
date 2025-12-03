// Advanced Hounsfield Units Ellipse ROI Measurement System
(function() {
    'use strict';
    
    // Standard Hounsfield Unit Values (WHO/Medical Standards)
    const HU_STANDARDS = {
        air: { min: -1000, max: -900, name: 'Air' },
        lung: { min: -900, max: -500, name: 'Lung' },
        fat: { min: -150, max: -50, name: 'Fat' },
        water: { min: -5, max: 5, name: 'Water' },
        csf: { min: 0, max: 15, name: 'CSF' },
        kidney: { min: 20, max: 45, name: 'Kidney' },
        blood: { min: 30, max: 45, name: 'Blood' },
        muscle: { min: 35, max: 55, name: 'Muscle' },
        gray_matter: { min: 37, max: 45, name: 'Gray Matter' },
        white_matter: { min: 25, max: 32, name: 'White Matter' },
        liver: { min: 40, max: 60, name: 'Liver' },
        soft_tissue: { min: 40, max: 80, name: 'Soft Tissue' },
        bone_cancellous: { min: 300, max: 400, name: 'Cancellous Bone' },
        bone_cortical: { min: 700, max: 3000, name: 'Cortical Bone' }
    };
    
    let currentROI = null;
    let isDrawingROI = false;
    let roiList = [];
    let roiCounter = 0;
    
    window.HounsfieldROI = {
        
        // Initialize ROI measurement system
        init: function() {
            this.createROIToolbar();
            this.setupEventListeners();
            console.log('Hounsfield ROI system initialized');
        },
        
        // Create ROI measurement toolbar
        createROIToolbar: function() {
            const toolbar = document.createElement('div');
            toolbar.id = 'roi-toolbar';
            toolbar.className = 'roi-toolbar';
            toolbar.innerHTML = `
                <div class="roi-controls">
                    <button id="roi-ellipse-btn" class="tool-btn" title="Draw Ellipse ROI">
                        <i class="fas fa-circle"></i> Ellipse ROI
                    </button>
                    <button id="roi-clear-btn" class="tool-btn" title="Clear All ROIs">
                        <i class="fas fa-trash"></i> Clear ROIs
                    </button>
                    <div class="roi-info">
                        <span id="roi-count">ROIs: 0</span>
                    </div>
                </div>
                <div id="roi-results" class="roi-results">
                    <h4>ROI Measurements</h4>
                    <div id="roi-list"></div>
                </div>
            `;
            
            // Add styles
            const style = document.createElement('style');
            style.textContent = `
                .roi-toolbar {
                    position: fixed;
                    top: 100px;
                    right: 20px;
                    width: 300px;
                    background: var(--card-bg, #252525);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 8px;
                    padding: 15px;
                    z-index: 1000;
                    color: var(--text-primary, #ffffff);
                    font-size: 12px;
                }
                .roi-controls {
                    display: flex;
                    gap: 10px;
                    align-items: center;
                    margin-bottom: 15px;
                }
                .tool-btn {
                    padding: 8px 12px;
                    background: var(--accent-color, #00d4ff);
                    color: #000;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 11px;
                    transition: all 0.2s;
                }
                .tool-btn:hover {
                    background: #00b8e6;
                }
                .tool-btn.active {
                    background: #ff6b35;
                }
                .roi-results {
                    max-height: 400px;
                    overflow-y: auto;
                }
                .roi-item {
                    background: var(--secondary-bg, #1a1a1a);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 4px;
                    padding: 10px;
                    margin: 8px 0;
                }
                .roi-stats {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 8px;
                    margin-top: 8px;
                }
                .roi-stat {
                    background: var(--primary-bg, #0a0a0a);
                    padding: 4px 8px;
                    border-radius: 3px;
                    font-size: 10px;
                }
                .hu-classification {
                    background: var(--success-color, #00ff88);
                    color: #000;
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-weight: bold;
                    font-size: 10px;
                }
                .roi-ellipse {
                    stroke: #00d4ff;
                    stroke-width: 2;
                    fill: rgba(0, 212, 255, 0.1);
                    cursor: move;
                }
                .roi-ellipse:hover {
                    stroke: #ff6b35;
                    stroke-width: 3;
                }
                .roi-handle {
                    fill: #00d4ff;
                    stroke: #ffffff;
                    stroke-width: 1;
                    cursor: pointer;
                }
            `;
            document.head.appendChild(style);
            
            // Add to viewport
            const viewport = document.querySelector('.viewer-container') || document.body;
            viewport.appendChild(toolbar);
        },
        
        // Setup event listeners
        setupEventListeners: function() {
            const ellipseBtn = document.getElementById('roi-ellipse-btn');
            const clearBtn = document.getElementById('roi-clear-btn');
            
            ellipseBtn?.addEventListener('click', () => this.toggleROIMode());
            clearBtn?.addEventListener('click', () => this.clearAllROIs());
            
            // Canvas/viewport mouse events
            const canvas = document.querySelector('#dicom-canvas') || 
                          document.querySelector('canvas') ||
                          document.querySelector('#viewport');
            
            if (canvas) {
                canvas.addEventListener('mousedown', (e) => this.onMouseDown(e));
                canvas.addEventListener('mousemove', (e) => this.onMouseMove(e));
                canvas.addEventListener('mouseup', (e) => this.onMouseUp(e));
            }
        },
        
        // Toggle ROI drawing mode
        toggleROIMode: function() {
            const btn = document.getElementById('roi-ellipse-btn');
            const measurementInfo = document.getElementById('measurement-info');
            isDrawingROI = !isDrawingROI;
            
            if (isDrawingROI) {
                btn.classList.add('active');
                btn.innerHTML = '<i class="fas fa-circle"></i> Drawing...';
                document.body.style.cursor = 'crosshair';
                // Show measurement instructions only when needed
                this.showMeasurementInstructions('Click and drag to draw ellipse ROI for measurement');
            } else {
                btn.classList.remove('active');
                btn.innerHTML = '<i class="fas fa-circle"></i> Ellipse ROI';
                document.body.style.cursor = 'default';
                // Hide measurement instructions when not measuring
                this.hideMeasurementInstructions();
            }
        },
        
        // Mouse event handlers
        onMouseDown: function(e) {
            if (!isDrawingROI) return;
            
            const rect = e.target.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            
            currentROI = {
                id: ++roiCounter,
                startX: x,
                startY: y,
                endX: x,
                endY: y,
                centerX: x,
                centerY: y,
                radiusX: 0,
                radiusY: 0,
                isDrawing: true
            };
        },
        
        onMouseMove: function(e) {
            if (!currentROI || !currentROI.isDrawing) return;
            
            const rect = e.target.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            
            currentROI.endX = x;
            currentROI.endY = y;
            currentROI.centerX = (currentROI.startX + x) / 2;
            currentROI.centerY = (currentROI.startY + y) / 2;
            currentROI.radiusX = Math.abs(x - currentROI.startX) / 2;
            currentROI.radiusY = Math.abs(y - currentROI.startY) / 2;
            
            this.drawROI(currentROI);
        },
        
        onMouseUp: function(e) {
            if (!currentROI || !currentROI.isDrawing) return;
            
            currentROI.isDrawing = false;
            
            // Only add if ROI has meaningful size
            if (currentROI.radiusX > 5 && currentROI.radiusY > 5) {
                this.calculateROIStatistics(currentROI);
                roiList.push(currentROI);
                this.updateROIList();
                this.toggleROIMode(); // Exit drawing mode
                this.showMeasurementComplete('Measurement completed successfully');
            }
            
            currentROI = null;
        },

        // Show measurement instructions
        showMeasurementInstructions: function(message) {
            let instructionsDiv = document.getElementById('measurement-instructions');
            if (!instructionsDiv) {
                instructionsDiv = document.createElement('div');
                instructionsDiv.id = 'measurement-instructions';
                instructionsDiv.style.cssText = `
                    position: fixed;
                    top: 70px;
                    left: 50%;
                    transform: translateX(-50%);
                    background: var(--accent-color, #00d4ff);
                    color: #000;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-size: 12px;
                    font-weight: bold;
                    z-index: 2000;
                    animation: slideDown 0.3s ease;
                `;
                document.body.appendChild(instructionsDiv);
            }
            instructionsDiv.textContent = message;
            instructionsDiv.style.display = 'block';
        },

        // Hide measurement instructions
        hideMeasurementInstructions: function() {
            const instructionsDiv = document.getElementById('measurement-instructions');
            if (instructionsDiv) {
                instructionsDiv.style.display = 'none';
            }
        },

        // Show measurement completion message
        showMeasurementComplete: function(message) {
            this.hideMeasurementInstructions();
            const completeDiv = document.createElement('div');
            completeDiv.style.cssText = `
                position: fixed;
                top: 70px;
                left: 50%;
                transform: translateX(-50%);
                background: var(--success-color, #00ff88);
                color: #000;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
                z-index: 2000;
            `;
            completeDiv.textContent = message;
            document.body.appendChild(completeDiv);
            setTimeout(() => {
                if (completeDiv.parentNode) {
                    completeDiv.remove();
                }
            }, 3000);
        },
        
        // Draw ROI ellipse on canvas
        drawROI: function(roi) {
            const canvas = document.querySelector('#dicom-canvas') || 
                          document.querySelector('canvas');
            
            if (!canvas) return;
            
            // Create or update SVG overlay
            let svg = document.getElementById('roi-overlay');
            if (!svg) {
                svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                svg.id = 'roi-overlay';
                svg.style.cssText = `
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    pointer-events: none;
                    z-index: 10;
                `;
                canvas.parentNode.style.position = 'relative';
                canvas.parentNode.appendChild(svg);
            }
            
            // Clear and redraw all ROIs
            svg.innerHTML = '';
            
            // Draw all existing ROIs
            roiList.forEach(r => this.drawEllipse(svg, r));
            
            // Draw current ROI being drawn
            if (roi && roi.isDrawing) {
                this.drawEllipse(svg, roi, true);
            }
        },
        
        // Draw individual ellipse
        drawEllipse: function(svg, roi, isTemp = false) {
            const ellipse = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
            ellipse.setAttribute('cx', roi.centerX);
            ellipse.setAttribute('cy', roi.centerY);
            ellipse.setAttribute('rx', roi.radiusX);
            ellipse.setAttribute('ry', roi.radiusY);
            ellipse.className = 'roi-ellipse';
            
            if (isTemp) {
                ellipse.style.strokeDasharray = '5,5';
            }
            
            svg.appendChild(ellipse);
            
            // Add label
            const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            text.setAttribute('x', roi.centerX);
            text.setAttribute('y', roi.centerY - roi.radiusY - 10);
            text.setAttribute('fill', '#00d4ff');
            text.setAttribute('font-size', '12');
            text.setAttribute('text-anchor', 'middle');
            text.textContent = `ROI ${roi.id}`;
            svg.appendChild(text);
        },
        
        // Calculate ROI statistics
        calculateROIStatistics: function(roi) {
            // Get pixel data from canvas (simplified - in real implementation, get from DICOM data)
            const canvas = document.querySelector('#dicom-canvas') || document.querySelector('canvas');
            if (!canvas) return;
            
            const ctx = canvas.getContext('2d');
            const imageData = ctx.getImageData(
                roi.centerX - roi.radiusX, 
                roi.centerY - roi.radiusY,
                roi.radiusX * 2, 
                roi.radiusY * 2
            );
            
            // Calculate statistics (simplified HU calculation)
            let pixelCount = 0;
            let sum = 0;
            let min = Infinity;
            let max = -Infinity;
            let values = [];
            
            for (let i = 0; i < imageData.data.length; i += 4) {
                // Convert grayscale to HU (simplified)
                const gray = imageData.data[i];
                const hu = (gray - 128) * 10; // Simplified HU conversion
                
                if (this.isInsideEllipse(i / 4, roi, imageData.width)) {
                    values.push(hu);
                    sum += hu;
                    min = Math.min(min, hu);
                    max = Math.max(max, hu);
                    pixelCount++;
                }
            }
            
            if (pixelCount > 0) {
                const mean = sum / pixelCount;
                const stdDev = this.calculateStdDev(values, mean);
                
                roi.statistics = {
                    pixelCount,
                    mean: Math.round(mean * 10) / 10,
                    min: Math.round(min * 10) / 10,
                    max: Math.round(max * 10) / 10,
                    stdDev: Math.round(stdDev * 10) / 10,
                    area: Math.PI * roi.radiusX * roi.radiusY,
                    classification: this.classifyHU(mean)
                };
            }
        },
        
        // Check if point is inside ellipse
        isInsideEllipse: function(pixelIndex, roi, width) {
            const x = pixelIndex % width;
            const y = Math.floor(pixelIndex / width);
            const dx = x - roi.radiusX;
            const dy = y - roi.radiusY;
            
            return ((dx * dx) / (roi.radiusX * roi.radiusX) + 
                    (dy * dy) / (roi.radiusY * roi.radiusY)) <= 1;
        },
        
        // Calculate standard deviation
        calculateStdDev: function(values, mean) {
            const variance = values.reduce((acc, val) => acc + Math.pow(val - mean, 2), 0) / values.length;
            return Math.sqrt(variance);
        },
        
        // Classify HU value according to medical standards
        classifyHU: function(hu) {
            for (const [key, standard] of Object.entries(HU_STANDARDS)) {
                if (hu >= standard.min && hu <= standard.max) {
                    return standard.name;
                }
            }
            return 'Unknown';
        },
        
        // Update ROI list display
        updateROIList: function() {
            const roiListEl = document.getElementById('roi-list');
            const roiCountEl = document.getElementById('roi-count');
            
            if (!roiListEl) return;
            
            roiCountEl.textContent = `ROIs: ${roiList.length}`;
            
            roiListEl.innerHTML = roiList.map(roi => `
                <div class="roi-item">
                    <div class="roi-header">
                        <strong>ROI ${roi.id}</strong>
                        <span class="hu-classification">${roi.statistics?.classification || 'Unknown'}</span>
                        <button onclick="HounsfieldROI.deleteROI(${roi.id})" class="delete-btn">×</button>
                    </div>
                    ${roi.statistics ? `
                        <div class="roi-stats">
                            <div class="roi-stat">Mean: ${roi.statistics.mean} HU</div>
                            <div class="roi-stat">Std Dev: ${roi.statistics.stdDev} HU</div>
                            <div class="roi-stat">Min: ${roi.statistics.min} HU</div>
                            <div class="roi-stat">Max: ${roi.statistics.max} HU</div>
                            <div class="roi-stat">Area: ${Math.round(roi.statistics.area)} px²</div>
                            <div class="roi-stat">Pixels: ${roi.statistics.pixelCount}</div>
                        </div>
                    ` : ''}
                </div>
            `).join('');
        },
        
        // Delete specific ROI
        deleteROI: function(roiId) {
            roiList = roiList.filter(roi => roi.id !== roiId);
            this.updateROIList();
            this.redrawAllROIs();
        },
        
        // Clear all ROIs
        clearAllROIs: function() {
            roiList = [];
            roiCounter = 0;
            this.updateROIList();
            
            const svg = document.getElementById('roi-overlay');
            if (svg) {
                svg.innerHTML = '';
            }
        },
        
        // Redraw all ROIs
        redrawAllROIs: function() {
            const svg = document.getElementById('roi-overlay');
            if (svg) {
                svg.innerHTML = '';
                roiList.forEach(roi => this.drawEllipse(svg, roi));
            }
        },
        
        // Export ROI measurements
        exportROIMeasurements: function() {
            const data = {
                timestamp: new Date().toISOString(),
                patient_id: window.currentPatient?.id || 'Unknown',
                study_id: window.currentStudy?.id || 'Unknown',
                measurements: roiList.map(roi => ({
                    roi_id: roi.id,
                    center: { x: roi.centerX, y: roi.centerY },
                    radii: { x: roi.radiusX, y: roi.radiusY },
                    statistics: roi.statistics
                }))
            };
            
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `ROI_measurements_${Date.now()}.json`;
            a.click();
            URL.revokeObjectURL(url);
        }
    };
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => HounsfieldROI.init());
    } else {
        HounsfieldROI.init();
    }
    
})();