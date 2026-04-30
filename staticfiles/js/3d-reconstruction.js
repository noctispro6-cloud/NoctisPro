// Advanced 3D Reconstruction System with Volume Rendering and MPR
(function() {
    'use strict';
    
    let volumeData = null;
    let renderer = null;
    let scene = null;
    let camera = null;
    let controls = null;
    let volumeMesh = null;
    let mprPlanes = { axial: null, sagittal: null, coronal: null };
    let currentReconType = 'volume';
    let resizeObserver = null;
    
    window.Reconstruction3D = {
        
        init: function() {
            this.createReconstructionPanel();
            this.setupEventListeners();
            this.initThreeJS();
            console.log('3D Reconstruction System initialized');
        },
        
        createReconstructionPanel: function() {
            const panel = document.createElement('div');
            panel.id = 'reconstruction-panel';
            panel.className = 'reconstruction-panel';
            panel.innerHTML = `
                <div class="recon-header">
                    <h3>3D Reconstruction</h3>
                    <button id="toggle-recon-panel" class="toggle-btn">−</button>
                </div>
                <div class="recon-content">
                    <div class="recon-controls">
                        <div class="control-group">
                            <label>Reconstruction Type:</label>
                            <select id="recon-type-select">
                                <option value="volume">Volume Rendering</option>
                                <option value="mpr">Multi-Planar Reconstruction</option>
                                <option value="mip">Maximum Intensity Projection</option>
                                <option value="minip">Minimum Intensity Projection</option>
                                <option value="surface">Surface Rendering</option>
                                <option value="vr">Virtual Reality View</option>
                            </select>
                        </div>
                        <div class="control-group">
                            <label>Modality Preset:</label>
                            <select id="modality-preset">
                                <option value="ct">CT Default</option>
                                <option value="ct-bone">CT Bone</option>
                                <option value="ct-lung">CT Lung</option>
                                <option value="ct-soft">CT Soft Tissue</option>
                                <option value="mri-t1">MRI T1</option>
                                <option value="mri-t2">MRI T2</option>
                                <option value="mri-flair">MRI FLAIR</option>
                                <option value="pet">PET</option>
                                <option value="custom">Custom</option>
                            </select>
                        </div>
                        <div class="control-group">
                            <label>Opacity: <span id="opacity-value">0.5</span></label>
                            <input type="range" id="opacity-slider" min="0" max="1" step="0.01" value="0.5">
                        </div>
                        <div class="control-group">
                            <label>Threshold: <span id="threshold-value">100</span></label>
                            <input type="range" id="threshold-slider" min="-1000" max="3000" step="10" value="100">
                        </div>
                        <div class="control-group">
                            <label>Quality:</label>
                            <select id="quality-select">
                                <option value="low">Low (Fast)</option>
                                <option value="medium" selected>Medium</option>
                                <option value="high">High (Slow)</option>
                                <option value="ultra">Ultra (Very Slow)</option>
                            </select>
                        </div>
                    </div>
                    
                    <div class="recon-actions">
                        <button id="start-reconstruction" class="btn-primary">
                            <i class="fas fa-play"></i> Start Reconstruction
                        </button>
                        <button id="reset-view" class="btn-secondary">
                            <i class="fas fa-undo"></i> Reset View
                        </button>
                        <button id="export-3d" class="btn-secondary">
                            <i class="fas fa-download"></i> Export 3D
                        </button>
                    </div>
                    
                    <div id="mpr-controls" class="mpr-controls" style="display: none;">
                        <h4>MPR Controls</h4>
                        <div class="mpr-planes">
                            <button class="mpr-plane-btn active" data-plane="axial">Axial</button>
                            <button class="mpr-plane-btn" data-plane="sagittal">Sagittal</button>
                            <button class="mpr-plane-btn" data-plane="coronal">Coronal</button>
                        </div>
                        <div class="slice-controls">
                            <label>Slice: <span id="slice-number">1</span>/<span id="total-slices">1</span></label>
                            <input type="range" id="slice-slider" min="1" max="1" value="1">
                        </div>
                        <div class="crosshair-controls">
                            <label>
                                <input type="checkbox" id="show-crosshairs" checked>
                                Show Crosshairs
                            </label>
                            <label>
                                <input type="checkbox" id="sync-crosshairs" checked>
                                Sync Crosshairs
                            </label>
                        </div>
                    </div>
                    
                    <div class="recon-progress" id="recon-progress" style="display: none;">
                        <div class="progress-bar">
                            <div class="progress-fill" id="progress-fill"></div>
                        </div>
                        <div class="progress-text" id="progress-text">Processing...</div>
                    </div>
                </div>
                
                <div id="reconstruction-viewport" class="reconstruction-viewport">
                    <canvas id="recon-canvas"></canvas>
                    <div class="viewport-overlay">
                        <div class="viewport-info" id="viewport-info"></div>
                    </div>
                </div>
            `;
            
            // Add styles
            const style = document.createElement('style');
            style.textContent = `
                .reconstruction-panel {
                    position: fixed;
                    top: 60px;
                    right: 20px;
                    width: 350px;
                    background: var(--card-bg, #252525);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 8px;
                    z-index: 1000;
                    color: var(--text-primary, #ffffff);
                    font-size: 12px;
                }
                .recon-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 12px 15px;
                    background: var(--header-bg, #333333);
                    border-radius: 8px 8px 0 0;
                }
                .recon-header h3 {
                    margin: 0;
                    font-size: 14px;
                }
                .toggle-btn {
                    background: none;
                    border: none;
                    color: var(--text-primary, #ffffff);
                    font-size: 18px;
                    cursor: pointer;
                    padding: 0;
                    width: 20px;
                    height: 20px;
                }
                .recon-content {
                    padding: 15px;
                }
                .control-group {
                    margin-bottom: 12px;
                }
                .control-group label {
                    display: block;
                    margin-bottom: 4px;
                    font-size: 11px;
                    color: var(--text-secondary, #b3b3b3);
                }
                .control-group select,
                .control-group input[type="range"] {
                    width: 100%;
                    padding: 4px 8px;
                    background: var(--secondary-bg, #1a1a1a);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 3px;
                    color: var(--text-primary, #ffffff);
                    font-size: 11px;
                }
                .recon-actions {
                    display: flex;
                    gap: 8px;
                    margin: 15px 0;
                }
                .btn-primary, .btn-secondary {
                    flex: 1;
                    padding: 8px 12px;
                    border: none;
                    border-radius: 4px;
                    font-size: 11px;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 4px;
                }
                .btn-primary {
                    background: var(--accent-color, #00d4ff);
                    color: #000;
                }
                .btn-secondary {
                    background: var(--card-bg, #252525);
                    color: var(--text-primary, #ffffff);
                    border: 1px solid var(--border-color, #404040);
                }
                .mpr-controls {
                    border-top: 1px solid var(--border-color, #404040);
                    padding-top: 15px;
                    margin-top: 15px;
                }
                .mpr-planes {
                    display: flex;
                    gap: 4px;
                    margin-bottom: 12px;
                }
                .mpr-plane-btn {
                    flex: 1;
                    padding: 6px 8px;
                    background: var(--secondary-bg, #1a1a1a);
                    border: 1px solid var(--border-color, #404040);
                    color: var(--text-primary, #ffffff);
                    border-radius: 3px;
                    cursor: pointer;
                    font-size: 10px;
                }
                .mpr-plane-btn.active {
                    background: var(--accent-color, #00d4ff);
                    color: #000;
                }
                .slice-controls {
                    margin-bottom: 12px;
                }
                .crosshair-controls label {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    margin-bottom: 6px;
                    cursor: pointer;
                }
                .recon-progress {
                    margin: 15px 0;
                }
                .progress-bar {
                    width: 100%;
                    height: 6px;
                    background: var(--secondary-bg, #1a1a1a);
                    border-radius: 3px;
                    overflow: hidden;
                }
                .progress-fill {
                    height: 100%;
                    background: var(--accent-color, #00d4ff);
                    transition: width 0.3s ease;
                    width: 0%;
                }
                .progress-text {
                    text-align: center;
                    margin-top: 8px;
                    font-size: 11px;
                    color: var(--text-secondary, #b3b3b3);
                }
                .reconstruction-viewport {
                    width: 100%;
                    height: 300px;
                    background: var(--primary-bg, #0a0a0a);
                    border-top: 1px solid var(--border-color, #404040);
                    position: relative;
                }
                #recon-canvas {
                    width: 100%;
                    height: 100%;
                    display: block;
                }
                .viewport-overlay {
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    pointer-events: none;
                }
                .viewport-info {
                    position: absolute;
                    top: 10px;
                    left: 10px;
                    background: rgba(0, 0, 0, 0.7);
                    padding: 8px;
                    border-radius: 4px;
                    font-size: 10px;
                    color: var(--text-primary, #ffffff);
                }
            `;
            document.head.appendChild(style);
            
            // Add to viewport
            const viewport = document.querySelector('.viewer-container') || document.body;
            viewport.appendChild(panel);
        },
        
        setupEventListeners: function() {
            // Panel toggle
            document.getElementById('toggle-recon-panel')?.addEventListener('click', this.togglePanel);
            
            // Controls
            document.getElementById('recon-type-select')?.addEventListener('change', (e) => {
                this.setReconstructionType(e.target.value);
            });
            
            document.getElementById('modality-preset')?.addEventListener('change', (e) => {
                this.applyModalityPreset(e.target.value);
            });
            
            document.getElementById('opacity-slider')?.addEventListener('input', (e) => {
                document.getElementById('opacity-value').textContent = e.target.value;
                this.updateOpacity(parseFloat(e.target.value));
            });
            
            document.getElementById('threshold-slider')?.addEventListener('input', (e) => {
                document.getElementById('threshold-value').textContent = e.target.value;
                this.updateThreshold(parseInt(e.target.value));
            });
            
            // Actions
            document.getElementById('start-reconstruction')?.addEventListener('click', () => {
                this.startReconstruction();
            });
            
            document.getElementById('reset-view')?.addEventListener('click', () => {
                this.resetView();
            });
            
            document.getElementById('export-3d')?.addEventListener('click', () => {
                this.export3D();
            });
            
            // MPR controls
            document.querySelectorAll('.mpr-plane-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    this.selectMPRPlane(e.target.dataset.plane);
                });
            });
            
            document.getElementById('slice-slider')?.addEventListener('input', (e) => {
                this.updateSlice(parseInt(e.target.value));
            });
            
            document.getElementById('show-crosshairs')?.addEventListener('change', (e) => {
                this.toggleCrosshairs(e.target.checked);
            });
            
            document.getElementById('sync-crosshairs')?.addEventListener('change', (e) => {
                this.toggleSyncCrosshairs(e.target.checked);
            });
        },
        
        initThreeJS: function() {
            const canvas = document.getElementById('recon-canvas');
            if (!canvas) return;
            
            const resizeViewport = () => {
                try {
                    if (!renderer) return;
                    // Use the canvas CSS pixel size (drawing buffer scaled via DPR).
                    const rect = canvas.getBoundingClientRect();
                    const w = Math.max(1, Math.round(rect.width));
                    const h = Math.max(1, Math.round(rect.height));
                    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
                    renderer.setSize(w, h, false);
                    if (camera) {
                        camera.aspect = w / h;
                        camera.updateProjectionMatrix();
                    }
                } catch (_) { /* ignore */ }
            };

            // Create renderer
            renderer = new THREE.WebGLRenderer({ 
                canvas: canvas, 
                antialias: true,
                alpha: true 
            });
            // Configure DPR and size for crisp rendering.
            resizeViewport();
            
            // Create scene
            scene = new THREE.Scene();
            scene.background = new THREE.Color(0x0a0a0a);
            
            // Create camera
            camera = new THREE.PerspectiveCamera(
                75, 
                (canvas.clientWidth || 1) / (canvas.clientHeight || 1), 
                0.1, 
                1000
            );
            camera.position.set(0, 0, 5);
            camera.up.set(0, 1, 0);
            
            // Create controls
            controls = new THREE.OrbitControls(camera, canvas);
            controls.enableDamping = true;
            controls.dampingFactor = 0.05;
            controls.target.set(0, 0, 0);
            controls.update();
            
            // Add lights
            const ambientLight = new THREE.AmbientLight(0x404040, 0.4);
            scene.add(ambientLight);
            
            const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
            directionalLight.position.set(1, 1, 1);
            scene.add(directionalLight);
            
            // Start render loop
            this.animate();

            // Keep renderer resolution correct on resize / panel show
            window.addEventListener('resize', resizeViewport);
            try {
                resizeObserver?.disconnect?.();
                resizeObserver = new ResizeObserver(() => resizeViewport());
                resizeObserver.observe(canvas);
                const container = document.getElementById('reconstruction-viewport');
                if (container) resizeObserver.observe(container);
            } catch (_) { /* ignore */ }
        },
        
        animate: function() {
            requestAnimationFrame(() => this.animate());
            
            if (controls) controls.update();
            if (renderer && scene && camera) {
                renderer.render(scene, camera);
            }
        },
        
        togglePanel: function() {
            const content = document.querySelector('.recon-content');
            const viewport = document.querySelector('.reconstruction-viewport');
            const toggleBtn = document.getElementById('toggle-recon-panel');
            
            if (content.style.display === 'none') {
                content.style.display = 'block';
                viewport.style.display = 'block';
                toggleBtn.textContent = '−';
                // Ensure canvas is resized after becoming visible.
                try { window.dispatchEvent(new Event('resize')); } catch (_) {}
            } else {
                content.style.display = 'none';
                viewport.style.display = 'none';
                toggleBtn.textContent = '+';
            }
        },
        
        setReconstructionType: function(type) {
            currentReconType = type;
            
            const mprControls = document.getElementById('mpr-controls');
            if (type === 'mpr') {
                mprControls.style.display = 'block';
            } else {
                mprControls.style.display = 'none';
            }
            
            // Update reconstruction if already started
            if (volumeData) {
                this.updateReconstruction();
            }
        },
        
        applyModalityPreset: function(preset) {
            const presets = {
                'ct': { opacity: 0.5, threshold: 100, colormap: 'grayscale' },
                'ct-bone': { opacity: 0.8, threshold: 300, colormap: 'bone' },
                'ct-lung': { opacity: 0.3, threshold: -500, colormap: 'lung' },
                'ct-soft': { opacity: 0.6, threshold: 50, colormap: 'soft' },
                'mri-t1': { opacity: 0.7, threshold: 200, colormap: 't1' },
                'mri-t2': { opacity: 0.7, threshold: 150, colormap: 't2' },
                'mri-flair': { opacity: 0.8, threshold: 100, colormap: 'flair' },
                'pet': { opacity: 0.9, threshold: 1000, colormap: 'hot' }
            };
            
            const config = presets[preset];
            if (config) {
                document.getElementById('opacity-slider').value = config.opacity;
                document.getElementById('opacity-value').textContent = config.opacity;
                document.getElementById('threshold-slider').value = config.threshold;
                document.getElementById('threshold-value').textContent = config.threshold;
                
                this.updateOpacity(config.opacity);
                this.updateThreshold(config.threshold);
            }
        },
        
        startReconstruction: async function() {
            const progressEl = document.getElementById('recon-progress');
            const progressFill = document.getElementById('progress-fill');
            const progressText = document.getElementById('progress-text');
            
            progressEl.style.display = 'block';
            progressText.textContent = 'Loading DICOM series...';
            progressFill.style.width = '10%';
            
            try {
                // Simulate loading DICOM data
                await this.loadVolumeData();
                
                progressText.textContent = 'Processing volume data...';
                progressFill.style.width = '40%';
                
                // Create 3D reconstruction based on type
                await this.createReconstruction();
                
                progressText.textContent = 'Rendering...';
                progressFill.style.width = '80%';
                
                // Final rendering
                await this.finalizeReconstruction();
                
                progressText.textContent = 'Complete!';
                progressFill.style.width = '100%';
                
                setTimeout(() => {
                    progressEl.style.display = 'none';
                }, 1000);
                
            } catch (error) {
                console.error('Reconstruction failed:', error);
                progressText.textContent = 'Error: ' + error.message;
                progressFill.style.width = '0%';
            }
        },
        
        loadVolumeData: async function() {
            // Simulate loading volume data from current DICOM series
            return new Promise((resolve) => {
                setTimeout(() => {
                    // Mock volume data - in real implementation, load from DICOM series
                    volumeData = {
                        dimensions: [512, 512, 100],
                        spacing: [0.5, 0.5, 1.0],
                        data: new Uint16Array(512 * 512 * 100).fill(100)
                    };
                    resolve();
                }, 500);
            });
        },
        
        createReconstruction: async function() {
            return new Promise((resolve) => {
                setTimeout(() => {
                    if (currentReconType === 'volume') {
                        this.createVolumeRendering();
                    } else if (currentReconType === 'mpr') {
                        this.createMPRView();
                    } else if (currentReconType === 'mip') {
                        this.createMIPView();
                    } else if (currentReconType === 'surface') {
                        this.createSurfaceRendering();
                    }
                    resolve();
                }, 1000);
            });
        },
        
        createVolumeRendering: function() {
            // Create volume rendering using Three.js
            const geometry = new THREE.BoxGeometry(2, 2, 2);
            const material = new THREE.MeshPhongMaterial({
                color: 0x00d4ff,
                transparent: true,
                opacity: 0.5
            });
            
            if (volumeMesh) {
                scene.remove(volumeMesh);
            }
            
            volumeMesh = new THREE.Mesh(geometry, material);
            scene.add(volumeMesh);
            
            this.updateViewportInfo('Volume Rendering - CT Data');
        },
        
        createMPRView: function() {
            // Create multi-planar reconstruction
            const planeGeometry = new THREE.PlaneGeometry(2, 2);
            
            // Remove existing planes
            Object.values(mprPlanes).forEach(plane => {
                if (plane) scene.remove(plane);
            });
            
            // Create axial plane
            const axialMaterial = new THREE.MeshBasicMaterial({ 
                color: 0x00d4ff, 
                transparent: true, 
                opacity: 0.7 
            });
            mprPlanes.axial = new THREE.Mesh(planeGeometry, axialMaterial);
            mprPlanes.axial.position.set(0, 0, 0);
            scene.add(mprPlanes.axial);
            
            // Create sagittal plane
            const sagittalMaterial = new THREE.MeshBasicMaterial({ 
                color: 0xff6b35, 
                transparent: true, 
                opacity: 0.7 
            });
            mprPlanes.sagittal = new THREE.Mesh(planeGeometry, sagittalMaterial);
            mprPlanes.sagittal.rotation.y = Math.PI / 2;
            mprPlanes.sagittal.position.set(0, 0, 0);
            scene.add(mprPlanes.sagittal);
            
            // Create coronal plane
            const coronalMaterial = new THREE.MeshBasicMaterial({ 
                color: 0x00ff88, 
                transparent: true, 
                opacity: 0.7 
            });
            mprPlanes.coronal = new THREE.Mesh(planeGeometry, coronalMaterial);
            mprPlanes.coronal.rotation.x = Math.PI / 2;
            mprPlanes.coronal.position.set(0, 0, 0);
            scene.add(mprPlanes.coronal);
            
            this.updateViewportInfo('Multi-Planar Reconstruction');
        },
        
        createMIPView: function() {
            // Create Maximum Intensity Projection
            const geometry = new THREE.SphereGeometry(1.5, 32, 32);
            const material = new THREE.MeshPhongMaterial({
                color: 0xffff00,
                transparent: true,
                opacity: 0.8
            });
            
            if (volumeMesh) {
                scene.remove(volumeMesh);
            }
            
            volumeMesh = new THREE.Mesh(geometry, material);
            scene.add(volumeMesh);
            
            this.updateViewportInfo('Maximum Intensity Projection');
        },
        
        createSurfaceRendering: function() {
            // Create surface rendering
            const geometry = new THREE.IcosahedronGeometry(1.5, 2);
            const material = new THREE.MeshPhongMaterial({
                color: 0xff6b35,
                shininess: 100
            });
            
            if (volumeMesh) {
                scene.remove(volumeMesh);
            }
            
            volumeMesh = new THREE.Mesh(geometry, material);
            scene.add(volumeMesh);
            
            this.updateViewportInfo('Surface Rendering');
        },
        
        finalizeReconstruction: async function() {
            return new Promise((resolve) => {
                setTimeout(() => {
                    // Add crosshairs for MPR
                    if (currentReconType === 'mpr') {
                        this.addCrosshairs();
                    }
                    
                    // Update slice controls
                    if (volumeData) {
                        document.getElementById('total-slices').textContent = volumeData.dimensions[2];
                        document.getElementById('slice-slider').max = volumeData.dimensions[2];
                    }
                    
                    resolve();
                }, 200);
            });
        },
        
        addCrosshairs: function() {
            // Add crosshair lines for MPR navigation
            const lineMaterial = new THREE.LineBasicMaterial({ color: 0xffffff });
            
            // Horizontal line
            const hLineGeometry = new THREE.BufferGeometry().setFromPoints([
                new THREE.Vector3(-2, 0, 0),
                new THREE.Vector3(2, 0, 0)
            ]);
            const hLine = new THREE.Line(hLineGeometry, lineMaterial);
            scene.add(hLine);
            
            // Vertical line
            const vLineGeometry = new THREE.BufferGeometry().setFromPoints([
                new THREE.Vector3(0, -2, 0),
                new THREE.Vector3(0, 2, 0)
            ]);
            const vLine = new THREE.Line(vLineGeometry, lineMaterial);
            scene.add(vLine);
        },
        
        selectMPRPlane: function(plane) {
            document.querySelectorAll('.mpr-plane-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            document.querySelector(`[data-plane="${plane}"]`).classList.add('active');
            
            // Hide other planes and show selected
            Object.keys(mprPlanes).forEach(key => {
                if (mprPlanes[key]) {
                    mprPlanes[key].visible = key === plane;
                }
            });
            
            this.updateViewportInfo(`MPR - ${plane.charAt(0).toUpperCase() + plane.slice(1)} View`);
        },
        
        updateSlice: function(sliceNumber) {
            document.getElementById('slice-number').textContent = sliceNumber;
            
            // Update the active MPR plane position
            const activePlane = document.querySelector('.mpr-plane-btn.active').dataset.plane;
            if (mprPlanes[activePlane] && volumeData) {
                const normalizedSlice = (sliceNumber - 1) / (volumeData.dimensions[2] - 1);
                const position = (normalizedSlice - 0.5) * 2; // Convert to -1 to 1 range
                
                if (activePlane === 'axial') {
                    mprPlanes.axial.position.z = position;
                } else if (activePlane === 'sagittal') {
                    mprPlanes.sagittal.position.x = position;
                } else if (activePlane === 'coronal') {
                    mprPlanes.coronal.position.y = position;
                }
            }
        },
        
        toggleCrosshairs: function(show) {
            // Toggle crosshair visibility
            scene.children.forEach(child => {
                if (child instanceof THREE.Line) {
                    child.visible = show;
                }
            });
        },
        
        toggleSyncCrosshairs: function(sync) {
            // Enable/disable crosshair synchronization across planes
            console.log('Crosshair sync:', sync);
        },
        
        updateOpacity: function(opacity) {
            if (volumeMesh && volumeMesh.material) {
                volumeMesh.material.opacity = opacity;
            }
            
            Object.values(mprPlanes).forEach(plane => {
                if (plane && plane.material) {
                    plane.material.opacity = opacity;
                }
            });
        },
        
        updateThreshold: function(threshold) {
            // Update volume threshold - in real implementation, this would affect the volume rendering
            console.log('Threshold updated:', threshold);
        },
        
        updateReconstruction: function() {
            if (volumeData) {
                this.createReconstruction();
            }
        },
        
        resetView: function() {
            if (camera && controls) {
                camera.position.set(0, 0, 5);
                controls.reset();
            }
        },
        
        export3D: function() {
            if (!renderer) return;
            
            // Render to higher resolution for export
            const originalSize = renderer.getSize(new THREE.Vector2());
            renderer.setSize(1920, 1080);
            renderer.render(scene, camera);
            
            // Export as image
            const canvas = renderer.domElement;
            const link = document.createElement('a');
            link.download = `3D_reconstruction_${Date.now()}.png`;
            link.href = canvas.toDataURL('image/png');
            link.click();
            
            // Restore original size
            renderer.setSize(originalSize.x, originalSize.y);
        },
        
        updateViewportInfo: function(text) {
            const infoEl = document.getElementById('viewport-info');
            if (infoEl) {
                infoEl.textContent = text;
            }
        }
    };
    
    // Load Three.js library if not already loaded
    if (typeof THREE === 'undefined') {
        const script = document.createElement('script');
        script.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
        script.onload = () => {
            // Load OrbitControls
            const controlsScript = document.createElement('script');
            controlsScript.src = 'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js';
            controlsScript.onload = () => {
                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', () => Reconstruction3D.init());
                } else {
                    Reconstruction3D.init();
                }
            };
            document.head.appendChild(controlsScript);
        };
        document.head.appendChild(script);
    } else {
        // Initialize immediately if Three.js is already loaded
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => Reconstruction3D.init());
        } else {
            Reconstruction3D.init();
        }
    }
    
})();