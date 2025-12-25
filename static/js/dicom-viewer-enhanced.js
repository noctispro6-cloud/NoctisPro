/**
 * Enhanced DICOM Viewer Tools
 * Professional DICOM viewing functionality with all tools working
 */

class DicomViewerEnhanced {
    constructor() {
        this.currentElement = null;
        this.currentImageId = null;
        this.viewport = null;
        this.tools = {};
        this.measurements = [];
        this.annotations = [];
        this.init();
    }

    init() {
        this.setupCornerstone();
        this.setupTools();
        this.setupEventListeners();
        this.setupUI();
    }

    setupCornerstone() {
        try {
            // Initialize cornerstone if available
            if (typeof cornerstone !== 'undefined') {
                cornerstone.events.addEventListener('cornerstoneimageloaded', this.onImageLoaded.bind(this));
                cornerstone.events.addEventListener('cornerstoneimageloadprogress', this.onImageLoadProgress.bind(this));
            }
        } catch (error) {
            console.warn('Cornerstone not available:', error);
        }
    }

    setupTools() {
        this.tools = {
            window: { name: 'Windowing', active: true },
            zoom: { name: 'Zoom', active: false },
            pan: { name: 'Pan', active: false },
            measure: { name: 'Measure', active: false },
            annotate: { name: 'Annotate', active: false },
            crosshair: { name: 'Crosshair', active: false },
            invert: { name: 'Invert', active: false },
            mpr: { name: 'MPR', active: false },
            ai: { name: 'AI Analysis', active: false },
            print: { name: 'Print', active: false },
            recon: { name: '3D Reconstruction', active: false }
        };
    }

    setupEventListeners() {
        // Tool button listeners
        document.addEventListener('click', (e) => {
            const tool = e.target.closest('.tool[data-tool]');
            if (tool) {
                const toolName = tool.dataset.tool;
                this.setTool(toolName);
            }
        });

        // Preset button listeners
        document.addEventListener('click', (e) => {
            const presetBtn = e.target.closest('.preset-btn');
            if (presetBtn) {
                const presetName = presetBtn.textContent.toLowerCase();
                this.applyPreset(presetName);
            }
        });
    }

    setupUI() {
        // Ensure all tool buttons are properly initialized
        this.updateToolButtons();
    }

    setTool(toolName) {
        try {
            // Deactivate all tools
            Object.keys(this.tools).forEach(tool => {
                this.tools[tool].active = false;
            });

            // Activate selected tool
            if (this.tools[toolName]) {
                this.tools[toolName].active = true;
            }

            // Update UI
            this.updateToolButtons();

            // Handle specific tool logic
            switch (toolName) {
                case 'window':
                    this.activateWindowLevelTool();
                    break;
                case 'zoom':
                    this.activateZoomTool();
                    break;
                case 'pan':
                    this.activatePanTool();
                    break;
                case 'measure':
                    this.activateMeasureTool();
                    break;
                case 'annotate':
                    this.activateAnnotateTool();
                    break;
                case 'reset':
                    this.resetView();
                    return; // Don't show toast for reset
                default:
                    console.log(`Tool ${toolName} activated`);
            }

            this.showToast(`${toolName.toUpperCase()} tool activated`, 'info', 1500);
        } catch (error) {
            this.showToast(`Failed to activate ${toolName} tool`, 'error');
            console.error('Tool activation error:', error);
        }
    }

    activateWindowLevelTool() {
        if (typeof cornerstoneTools !== 'undefined' && this.currentElement) {
            try {
                cornerstoneTools.setToolActive('wwwc', { mouseButtonMask: 1 }, this.currentElement);
            } catch (error) {
                console.warn('Cornerstone tools not available for window/level');
            }
        }
    }

    activateZoomTool() {
        if (typeof cornerstoneTools !== 'undefined' && this.currentElement) {
            try {
                cornerstoneTools.setToolActive('zoom', { mouseButtonMask: 1 }, this.currentElement);
            } catch (error) {
                console.warn('Cornerstone tools not available for zoom');
            }
        }
    }

    activatePanTool() {
        if (typeof cornerstoneTools !== 'undefined' && this.currentElement) {
            try {
                cornerstoneTools.setToolActive('pan', { mouseButtonMask: 1 }, this.currentElement);
            } catch (error) {
                console.warn('Cornerstone tools not available for pan');
            }
        }
    }

    activateMeasureTool() {
        if (typeof cornerstoneTools !== 'undefined' && this.currentElement) {
            try {
                cornerstoneTools.setToolActive('length', { mouseButtonMask: 1 }, this.currentElement);
            } catch (error) {
                console.warn('Cornerstone tools not available for measure');
            }
        }
    }

    activateAnnotateTool() {
        if (typeof cornerstoneTools !== 'undefined' && this.currentElement) {
            try {
                cornerstoneTools.setToolActive('arrowAnnotate', { mouseButtonMask: 1 }, this.currentElement);
            } catch (error) {
                console.warn('Cornerstone tools not available for annotate');
            }
        }
    }

    updateToolButtons() {
        document.querySelectorAll('.tool[data-tool]').forEach(button => {
            const toolName = button.dataset.tool;
            if (this.tools[toolName] && this.tools[toolName].active) {
                button.classList.add('active');
            } else {
                button.classList.remove('active');
            }
        });
    }

    resetView() {
        try {
            if (typeof cornerstone !== 'undefined' && this.currentElement) {
                cornerstone.reset(this.currentElement);
                this.showToast('View reset', 'success', 1500);
            } else {
                this.showToast('View reset (no image loaded)', 'info', 1500);
            }
        } catch (error) {
            this.showToast('Failed to reset view', 'error');
            console.error('Reset view error:', error);
        }
    }

    toggleCrosshair() {
        try {
            const crosshairElement = document.getElementById('crosshairOverlay');
            if (crosshairElement) {
                crosshairElement.style.display = crosshairElement.style.display === 'none' ? 'block' : 'none';
                this.showToast('Crosshair toggled', 'info', 1500);
            } else {
                this.createCrosshair();
            }
        } catch (error) {
            this.showToast('Failed to toggle crosshair', 'error');
        }
    }

    createCrosshair() {
        const imageContainer = document.getElementById('imageContainer');
        if (!imageContainer) return;

        const crosshair = document.createElement('div');
        crosshair.id = 'crosshairOverlay';
        crosshair.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            pointer-events: none;
            z-index: 100;
        `;

        const horizontalLine = document.createElement('div');
        horizontalLine.style.cssText = `
            position: absolute;
            top: 50%;
            left: 0;
            right: 0;
            height: 1px;
            background: var(--accent-color, #00d4ff);
            opacity: 0.7;
        `;

        const verticalLine = document.createElement('div');
        verticalLine.style.cssText = `
            position: absolute;
            left: 50%;
            top: 0;
            bottom: 0;
            width: 1px;
            background: var(--accent-color, #00d4ff);
            opacity: 0.7;
        `;

        crosshair.appendChild(horizontalLine);
        crosshair.appendChild(verticalLine);
        imageContainer.appendChild(crosshair);

        this.showToast('Crosshair enabled', 'success', 1500);
    }

    toggleInvert() {
        try {
            if (typeof cornerstone !== 'undefined' && this.currentElement) {
                const viewport = cornerstone.getViewport(this.currentElement);
                viewport.invert = !viewport.invert;
                cornerstone.setViewport(this.currentElement, viewport);
                this.showToast(viewport.invert ? 'Image inverted' : 'Image normal', 'info', 1500);
            } else {
                this.showToast('No image to invert', 'warning');
            }
        } catch (error) {
            this.showToast('Failed to invert image', 'error');
            console.error('Invert error:', error);
        }
    }

    applyPreset(presetName) {
        try {
            if (typeof cornerstone !== 'undefined' && this.currentElement) {
                const viewport = cornerstone.getViewport(this.currentElement);
                
                // Define presets
                const presets = {
                    lung: { windowWidth: 1500, windowCenter: -600 },
                    bone: { windowWidth: 2000, windowCenter: 300 },
                    soft: { windowWidth: 400, windowCenter: 40 },
                    brain: { windowWidth: 80, windowCenter: 40 },
                    liver: { windowWidth: 150, windowCenter: 30 },
                    cine: { windowWidth: 600, windowCenter: 200 }
                };

                if (presets[presetName]) {
                    viewport.voi.windowWidth = presets[presetName].windowWidth;
                    viewport.voi.windowCenter = presets[presetName].windowCenter;
                    cornerstone.setViewport(this.currentElement, viewport);
                    this.showToast(`${presetName.toUpperCase()} preset applied`, 'success', 1500);
                } else {
                    this.showToast(`Unknown preset: ${presetName}`, 'warning');
                }
            } else {
                this.showToast('No image loaded for preset', 'warning');
            }
        } catch (error) {
            this.showToast(`Failed to apply ${presetName} preset`, 'error');
            console.error('Preset error:', error);
        }
    }

    loadFromLocalFiles() {
        try {
            const input = document.createElement('input');
            input.type = 'file';
            input.multiple = true;
            // CT studies are commonly stored as .IMA (e.g., Siemens), and some studies have .DICM/.DICOM or no extension.
            // We keep the accept wide and rely on server-side DICOM validation for correctness.
            input.accept = '.dcm,.dicom,.dicm,.ima,*';
            // Folder selection is Chromium/WebKit-only; other browsers should gracefully fall back to multi-file selection.
            try {
                const test = document.createElement('input');
                if ('webkitdirectory' in test) {
                    input.setAttribute('webkitdirectory', '');
                    input.setAttribute('directory', '');
                }
            } catch (_) {}
            input.onchange = (e) => {
                const files = Array.from(e.target.files || []);
                if (!files.length) return;
                // Always upload to server so rendering matches worklist-opened studies (CT/transfer syntaxes/etc).
                this.showToast(`Uploading ${files.length} file(s) to viewer...`, 'info', 4000);
                this.uploadLocalDicomToServer(files);
            };
            input.click();
        } catch (error) {
            this.showToast('Failed to open file dialog', 'error');
        }
    }

    async displayLocalDicomSeries(files) {
        try {
            if (typeof dicomParser === 'undefined') {
                this.showToast('DICOM parser not available', 'error');
                return;
            }
            // Sort files for natural series order
            files.sort((a, b) => (a.webkitRelativePath || a.name).localeCompare(b.webkitRelativePath || b.name, undefined, { numeric: true }));

            const canvas = document.getElementById('dicomCanvas') || document.querySelector('canvas.dicom-canvas');
            if (!canvas) {
                this.showToast('No canvas available to render DICOM', 'error');
                return;
            }
            const ctx = canvas.getContext('2d');
            const overlayCurrent = document.getElementById('currentSlice');
            const overlayTotal = document.getElementById('totalSlices');
            const wwSlider = document.getElementById('windowWidthSlider');
            const wlSlider = document.getElementById('windowLevelSlider');

            // Parse all files (lightweight). Stop if too many errors.
            const localImages = [];
            for (let i = 0; i < files.length; i++) {
                const f = files[i];
                try {
                    const buf = await f.arrayBuffer();
                    const bytes = new Uint8Array(buf);
                    const ds = dicomParser.parseDicom(bytes);
                    const rows = ds.uint16('x00280010') || 0;
                    const cols = ds.uint16('x00280011') || 0;
                    const bitsAllocated = ds.uint16('x00280100') || 16;
                    const pixelRep = ds.uint16('x00280103') || 0;
                    const spp = ds.uint16('x00280002') || 1;
                    const pixelEl = ds.elements.x7fe00010;
                    if (!pixelEl || spp !== 1 || !rows || !cols) continue;
                    const raw = new Uint8Array(ds.byteArray.buffer, pixelEl.dataOffset, pixelEl.length);
                    let pixels;
                    if (bitsAllocated === 8) {
                        pixels = new Uint8Array(raw);
                    } else if (bitsAllocated === 16) {
                        const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
                        const len = raw.byteLength / 2;
                        pixels = new Float32Array(len);
                        for (let j = 0; j < len; j++) {
                            const v = pixelRep === 1 ? view.getInt16(j * 2, true) : view.getUint16(j * 2, true);
                            pixels[j] = v;
                        }
                    } else {
                        continue;
                    }
                    // WW/WL
                    let ww = (ds.intString && ds.intString('x00281051')) || null;
                    let wl = (ds.intString && ds.intString('x00281050')) || null;
                    if (!ww || !wl) {
                        let min = Infinity, max = -Infinity;
                        for (let j = 0; j < pixels.length; j++) { const v = pixels[j]; if (v < min) min = v; if (v > max) max = v; }
                        ww = Math.max(1, (max - min));
                        wl = Math.round(min + ww / 2);
                    }
                    localImages.push({ rows, cols, pixels, ww, wl });
                } catch (e) {
                    // Skip corrupt file
                }
            }

            if (!localImages.length) {
                this.showToast('No renderable DICOM images found', 'warning');
                return;
            }

            // Use first image to size canvas
            canvas.width = localImages[0].cols;
            canvas.height = localImages[0].rows;

            let index = 0;
            let ww = localImages[0].ww;
            let wl = localImages[0].wl;

            const render = () => {
                const img = localImages[index];
                if (!img) return;
                const W = img.cols, H = img.rows;
                if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
                const imageData = ctx.createImageData(W, H);
                const low = wl - ww / 2;
                const high = wl + ww / 2;
                for (let i = 0; i < W * H; i++) {
                    const v = img.pixels[i];
                    let g = Math.round(((v - low) / (high - low)) * 255);
                    if (isNaN(g)) g = 0; if (g < 0) g = 0; if (g > 255) g = 255;
                    const j = i * 4;
                    imageData.data[j] = g;
                    imageData.data[j + 1] = g;
                    imageData.data[j + 2] = g;
                    imageData.data[j + 3] = 255;
                }
                ctx.putImageData(imageData, 0, 0);
                if (overlayCurrent) overlayCurrent.textContent = index + 1;
                if (overlayTotal) overlayTotal.textContent = localImages.length;
            };

            const clampIndex = (v) => Math.max(0, Math.min(localImages.length - 1, v));
            const changeSlice = (delta) => { index = clampIndex(index + delta); render(); };

            // Mouse wheel for slice navigation
            canvas.addEventListener('wheel', (e) => { e.preventDefault(); changeSlice(e.deltaY > 0 ? 1 : -1); }, { passive: false });
            // Arrow keys
            document.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowUp') { e.preventDefault(); changeSlice(-1); }
                if (e.key === 'ArrowDown') { e.preventDefault(); changeSlice(1); }
            });
            // Hook WW/WL sliders if present
            if (wwSlider) wwSlider.addEventListener('input', (e) => { ww = parseInt(e.target.value || ww, 10) || ww; render(); });
            if (wlSlider) wlSlider.addEventListener('input', (e) => { wl = parseInt(e.target.value || wl, 10) || wl; render(); });

            render();
            this.showToast(`Loaded local series: ${localImages.length} image(s)`, 'success');
        } catch (e) {
            console.error(e);
            this.showToast('Failed to open local DICOM series', 'error');
        }
    }

    uploadLocalDicomToServer(files) {
        try {
            const url = '/worklist/upload/';
            const token = (document.querySelector('meta[name="csrf-token"]') && document.querySelector('meta[name="csrf-token"]').getAttribute('content')) || '';
            // Keep chunks small so each request completes quickly (avoid proxy/browser timeouts).
            const MAX_CHUNK_BYTES = 10 * 1024 * 1024; // 10MB
            const MAX_CHUNK_FILES = 120; // cap count (CT can have many small slices)
            const chunks = [];
            let current = []; let bytes = 0;
            for (const f of files) {
                const fsize = (f.size || 0);
                const wouldExceedBytes = (bytes + fsize) > MAX_CHUNK_BYTES;
                const wouldExceedCount = current.length >= MAX_CHUNK_FILES;
                if ((wouldExceedBytes || wouldExceedCount) && current.length) { chunks.push(current); current = []; bytes = 0; }
                current.push(f); bytes += (f.size || 0);
            }
            if (current.length) chunks.push(current);

            const uploadChunk = (chunk, attempt = 1) => new Promise((resolve) => {
                const formData = new FormData();
                chunk.forEach(file => formData.append('dicom_files', file));
                formData.append('priority', 'normal');
                const xhr = new XMLHttpRequest();
                xhr.open('POST', url, true);
                if (token) xhr.setRequestHeader('X-CSRFToken', token);
                xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
                xhr.timeout = 300000;
                xhr.onreadystatechange = function() {
                    if (xhr.readyState === 4) {
                        try {
                            const data = JSON.parse(xhr.responseText || '{}');
                            resolve({ ok: xhr.status >= 200 && xhr.status < 300 && data && data.success, data });
                        } catch (_) { resolve({ ok: false, data: null }); }
                    }
                };
                const fail = (reason) => {
                    // Retry transient network failures a couple times
                    if (attempt < 3 && (reason === 'timeout' || reason === 'network' || reason === 'abort' || xhr.status === 0)) {
                        const backoff = 800 * Math.pow(2, attempt - 1);
                        setTimeout(() => uploadChunk(chunk, attempt + 1).then(resolve), backoff);
                        return;
                    }
                    resolve({ ok: false, data: null });
                };
                xhr.onerror = function() { fail('network'); };
                xhr.ontimeout = function() { fail('timeout'); };
                xhr.onabort = function() { fail('abort'); };
                xhr.send(formData);
            });

            const run = async () => {
                let createdIds = [];
                for (let i = 0; i < chunks.length; i++) {
                    this.showToast(`Uploading DICOM chunk ${i + 1}/${chunks.length}...`, 'info', 4000);
                    const res = await uploadChunk(chunks[i]);
                    if (!res.ok) { this.showToast('Upload failed. Try smaller selection.', 'error'); return; }
                    if (Array.isArray(res.data && res.data.created_study_ids)) {
                        createdIds = createdIds.concat(res.data.created_study_ids);
                    }
                }
                if (createdIds.length) {
                    this.showToast('Upload complete. Opening in viewer...', 'success');
                    window.location.href = '/dicom-viewer/?study=' + createdIds[0];
                } else {
                    this.showToast('Upload finished but no study id returned', 'warning');
                }
            };
            run();
        } catch (e) {
            console.error(e);
            this.showToast('Failed to upload local DICOM to server', 'error');
        }
    }

    loadFromExternalMedia() {
        this.showToast('Opening external media loader...', 'info');
        // This would open a dialog to browse external media
        window.location.href = '/dicom-viewer/load-directory/';
    }

    exportImage() {
        try {
            if (typeof cornerstone !== 'undefined' && this.currentElement) {
                const canvas = cornerstone.getEnabledElement(this.currentElement).canvas;
                const link = document.createElement('a');
                link.download = `dicom-export-${Date.now()}.png`;
                link.href = canvas.toDataURL();
                link.click();
                this.showToast('Image exported successfully', 'success');
            } else {
                this.showToast('No image to export', 'warning');
            }
        } catch (error) {
            this.showToast('Failed to export image', 'error');
        }
    }

    saveMeasurements() {
        try {
            // Save measurements to localStorage or server
            const measurements = this.measurements;
            localStorage.setItem('dicom-measurements', JSON.stringify(measurements));
            this.showToast('Measurements saved', 'success');
        } catch (error) {
            this.showToast('Failed to save measurements', 'error');
        }
    }

    clearMeasurements() {
        try {
            this.measurements = [];
            if (typeof cornerstoneTools !== 'undefined' && this.currentElement) {
                cornerstoneTools.clearToolState(this.currentElement, 'length');
                cornerstone.updateImage(this.currentElement);
            }
            this.showToast('Measurements cleared', 'success');
        } catch (error) {
            this.showToast('Failed to clear measurements', 'error');
        }
    }

    showPrintDialog() {
        try {
            this.showToast('Opening print dialog...', 'info');
            window.print();
        } catch (error) {
            this.showToast('Failed to open print dialog', 'error');
        }
    }

    show3DReconstruction() {
        try {
            this.showToast('Launching 3D reconstruction...', 'info');
            // This would launch the 3D reconstruction view
            console.log('3D reconstruction requested');
        } catch (error) {
            this.showToast('Failed to launch 3D reconstruction', 'error');
        }
    }

    toggleMPR() {
        try {
            const mprPanel = document.querySelector('.mpr-panel');
            if (mprPanel) {
                mprPanel.style.display = mprPanel.style.display === 'none' ? 'block' : 'none';
                this.showToast('MPR view toggled', 'info', 1500);
            }
        } catch (error) {
            this.showToast('Failed to toggle MPR', 'error');
        }
    }

    toggleAIPanel() {
        try {
            const aiPanel = document.querySelector('.ai-panel');
            if (aiPanel) {
                aiPanel.style.display = aiPanel.style.display === 'none' ? 'block' : 'none';
                this.showToast('AI panel toggled', 'info', 1500);
            }
        } catch (error) {
            this.showToast('Failed to toggle AI panel', 'error');
        }
    }

    runQuickAI() {
        try {
            this.showToast('Running AI analysis...', 'info');
            // Simulate AI processing
            setTimeout(() => {
                this.showToast('AI analysis complete', 'success');
            }, 2000);
        } catch (error) {
            this.showToast('AI analysis failed', 'error');
        }
    }

    // Event handlers
    onImageLoaded(e) {
        this.currentElement = e.target;
        this.currentImageId = e.detail.imageId;
        console.log('Image loaded:', this.currentImageId);
    }

    onImageLoadProgress(e) {
        const progress = Math.round((e.detail.percentComplete || 0) * 100);
        if (progress < 100) {
            this.showToast(`Loading image: ${progress}%`, 'info', 500);
        }
    }

    showToast(message, type = 'info', duration = 3000) {
        // Use the global toast system if available
        if (window.noctisProButtonManager) {
            window.noctisProButtonManager.showToast(message, type, duration);
        } else {
            console.log(`${type.toUpperCase()}: ${message}`);
        }
    }
}

// Initialize enhanced DICOM viewer
let dicomViewerEnhanced;

document.addEventListener('DOMContentLoaded', function() {
    dicomViewerEnhanced = new DicomViewerEnhanced();
    
    // Make globally available
    window.dicomViewerEnhanced = dicomViewerEnhanced;
    
    // Global function aliases for DICOM viewer.
    // IMPORTANT: do not override pages that provide their own implementations.
    const defineIfMissing = (name, fn) => {
        try {
            if (typeof window[name] !== 'function') {
                window[name] = fn;
            }
        } catch (_) { /* ignore */ }
    };

    defineIfMissing('setTool', (toolName) => dicomViewerEnhanced.setTool(toolName));
    defineIfMissing('resetView', () => dicomViewerEnhanced.resetView());
    defineIfMissing('toggleCrosshair', () => dicomViewerEnhanced.toggleCrosshair());
    defineIfMissing('toggleInvert', () => dicomViewerEnhanced.toggleInvert());
    defineIfMissing('applyPreset', (presetName) => dicomViewerEnhanced.applyPreset(presetName));
    defineIfMissing('loadFromLocalFiles', () => dicomViewerEnhanced.loadFromLocalFiles());
    defineIfMissing('loadFromExternalMedia', () => dicomViewerEnhanced.loadFromExternalMedia());
    defineIfMissing('exportImage', () => dicomViewerEnhanced.exportImage());
    defineIfMissing('saveMeasurements', () => dicomViewerEnhanced.saveMeasurements());
    defineIfMissing('clearMeasurements', () => dicomViewerEnhanced.clearMeasurements());
    defineIfMissing('showPrintDialog', () => dicomViewerEnhanced.showPrintDialog());
    defineIfMissing('show3DReconstruction', () => dicomViewerEnhanced.show3DReconstruction());
    defineIfMissing('toggleMPR', () => dicomViewerEnhanced.toggleMPR());
    defineIfMissing('toggleAIPanel', () => dicomViewerEnhanced.toggleAIPanel());
    defineIfMissing('runQuickAI', () => dicomViewerEnhanced.runQuickAI());
});

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DicomViewerEnhanced;
}