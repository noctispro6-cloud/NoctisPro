// Advanced Movable and Resizable Annotations System
(function() {
    'use strict';
    
    let annotations = [];
    let annotationCounter = 0;
    let selectedAnnotation = null;
    let isDragging = false;
    let isResizing = false;
    let dragOffset = { x: 0, y: 0 };
    let currentTool = 'select';
    
    window.AnnotationSystem = {
        
        init: function() {
            this.createAnnotationToolbar();
            this.setupEventListeners();
            console.log('Movable Annotations System initialized');
        },
        
        createAnnotationToolbar: function() {
            const toolbar = document.createElement('div');
            toolbar.id = 'annotation-toolbar';
            toolbar.className = 'annotation-toolbar';
            toolbar.innerHTML = `
                <div class="annotation-controls">
                    <button id="text-annotation-btn" class="tool-btn" title="Add Text Annotation">
                        <i class="fas fa-font"></i> Text
                    </button>
                    <button id="arrow-annotation-btn" class="tool-btn" title="Add Arrow">
                        <i class="fas fa-long-arrow-alt-right"></i> Arrow
                    </button>
                    <button id="select-annotation-btn" class="tool-btn active" title="Select/Move">
                        <i class="fas fa-mouse-pointer"></i> Select
                    </button>
                    <button id="clear-annotations-btn" class="tool-btn" title="Clear All">
                        <i class="fas fa-trash"></i> Clear
                    </button>
                </div>
                <div class="annotation-properties">
                    <div class="property-group">
                        <label>Font Size:</label>
                        <input type="range" id="font-size-slider" min="8" max="48" value="16">
                        <span id="font-size-value">16px</span>
                    </div>
                    <div class="property-group">
                        <label>Color:</label>
                        <input type="color" id="annotation-color" value="#00d4ff">
                    </div>
                    <div class="property-group">
                        <label>Background:</label>
                        <input type="checkbox" id="annotation-background">
                        <input type="color" id="background-color" value="#000000" disabled>
                    </div>
                </div>
                <div id="annotation-list" class="annotation-list">
                    <h4>Annotations</h4>
                    <div id="annotations-container"></div>
                </div>
            `;
            
            // Add styles
            const style = document.createElement('style');
            style.textContent = `
                .annotation-toolbar {
                    position: fixed;
                    top: 100px;
                    left: 20px;
                    width: 280px;
                    background: var(--card-bg, #252525);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 8px;
                    padding: 15px;
                    z-index: 1000;
                    color: var(--text-primary, #ffffff);
                    font-size: 12px;
                }
                .annotation-controls {
                    display: flex;
                    gap: 8px;
                    margin-bottom: 15px;
                    flex-wrap: wrap;
                }
                .annotation-properties {
                    margin-bottom: 15px;
                }
                .property-group {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    margin-bottom: 8px;
                }
                .property-group label {
                    min-width: 70px;
                    font-size: 11px;
                }
                .property-group input[type="range"] {
                    flex: 1;
                }
                .property-group input[type="color"] {
                    width: 30px;
                    height: 25px;
                    border: none;
                    border-radius: 3px;
                    cursor: pointer;
                }
                .annotation-list {
                    max-height: 200px;
                    overflow-y: auto;
                }
                .annotation-item {
                    background: var(--secondary-bg, #1a1a1a);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 4px;
                    padding: 8px;
                    margin: 5px 0;
                    cursor: pointer;
                }
                .annotation-item:hover {
                    background: var(--primary-bg, #0a0a0a);
                }
                .annotation-item.selected {
                    border-color: var(--accent-color, #00d4ff);
                }
                .annotation-overlay {
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    pointer-events: none;
                    z-index: 100;
                }
                .annotation-text {
                    position: absolute;
                    pointer-events: all;
                    cursor: move;
                    user-select: none;
                    padding: 4px 8px;
                    border-radius: 3px;
                    font-family: Arial, sans-serif;
                    white-space: nowrap;
                    min-width: 50px;
                    min-height: 20px;
                }
                .annotation-text:hover {
                    box-shadow: 0 0 8px rgba(0, 212, 255, 0.5);
                }
                .annotation-text.selected {
                    border: 2px solid var(--accent-color, #00d4ff);
                }
                .annotation-text.editing {
                    cursor: text;
                    user-select: text;
                }
                .resize-handle {
                    position: absolute;
                    width: 8px;
                    height: 8px;
                    background: var(--accent-color, #00d4ff);
                    border: 1px solid #fff;
                    border-radius: 50%;
                    cursor: se-resize;
                }
                .resize-handle.bottom-right {
                    bottom: -4px;
                    right: -4px;
                }
                .annotation-arrow {
                    stroke: var(--accent-color, #00d4ff);
                    stroke-width: 2;
                    fill: none;
                    marker-end: url(#arrowhead);
                    pointer-events: all;
                    cursor: move;
                }
                .annotation-arrow:hover {
                    stroke-width: 3;
                    stroke: #ff6b35;
                }
            `;
            document.head.appendChild(style);
            
            // Add to viewport
            const viewport = document.querySelector('.viewer-container') || document.body;
            viewport.appendChild(toolbar);
        },
        
        setupEventListeners: function() {
            // Tool buttons
            document.getElementById('text-annotation-btn')?.addEventListener('click', () => this.setTool('text'));
            document.getElementById('arrow-annotation-btn')?.addEventListener('click', () => this.setTool('arrow'));
            document.getElementById('select-annotation-btn')?.addEventListener('click', () => this.setTool('select'));
            document.getElementById('clear-annotations-btn')?.addEventListener('click', () => this.clearAllAnnotations());
            
            // Property controls
            const fontSizeSlider = document.getElementById('font-size-slider');
            const fontSizeValue = document.getElementById('font-size-value');
            fontSizeSlider?.addEventListener('input', (e) => {
                fontSizeValue.textContent = e.target.value + 'px';
                this.updateSelectedAnnotation('fontSize', e.target.value + 'px');
            });
            
            document.getElementById('annotation-color')?.addEventListener('change', (e) => {
                this.updateSelectedAnnotation('color', e.target.value);
            });
            
            const backgroundCheckbox = document.getElementById('annotation-background');
            const backgroundColorInput = document.getElementById('background-color');
            backgroundCheckbox?.addEventListener('change', (e) => {
                backgroundColorInput.disabled = !e.target.checked;
                this.updateSelectedAnnotation('hasBackground', e.target.checked);
                if (e.target.checked) {
                    this.updateSelectedAnnotation('backgroundColor', backgroundColorInput.value);
                }
            });
            
            backgroundColorInput?.addEventListener('change', (e) => {
                this.updateSelectedAnnotation('backgroundColor', e.target.value);
            });
            
            // Canvas/viewport events
            const canvas = document.querySelector('#dicom-canvas') || 
                          document.querySelector('canvas') ||
                          document.querySelector('#viewport');
            
            if (canvas) {
                canvas.addEventListener('click', (e) => this.onCanvasClick(e));
                canvas.addEventListener('mousedown', (e) => this.onMouseDown(e));
                canvas.addEventListener('mousemove', (e) => this.onMouseMove(e));
                canvas.addEventListener('mouseup', (e) => this.onMouseUp(e));
            }
            
            // Keyboard events
            document.addEventListener('keydown', (e) => this.onKeyDown(e));
        },
        
        setTool: function(tool) {
            currentTool = tool;
            
            // Update button states
            document.querySelectorAll('.tool-btn').forEach(btn => btn.classList.remove('active'));
            document.getElementById(tool + '-annotation-btn')?.classList.add('active');
            
            // Update cursor
            const canvas = document.querySelector('#dicom-canvas') || document.querySelector('canvas');
            if (canvas) {
                canvas.style.cursor = tool === 'select' ? 'default' : 'crosshair';
            }
        },
        
        onCanvasClick: function(e) {
            if (currentTool === 'text') {
                this.createTextAnnotation(e);
            } else if (currentTool === 'arrow') {
                this.createArrowAnnotation(e);
            }
        },
        
        createTextAnnotation: function(e) {
            const rect = e.target.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            
            const annotation = {
                id: ++annotationCounter,
                type: 'text',
                x: x,
                y: y,
                text: 'Double-click to edit',
                fontSize: '16px',
                color: '#00d4ff',
                hasBackground: false,
                backgroundColor: '#000000',
                width: 150,
                height: 30
            };
            
            annotations.push(annotation);
            this.renderAnnotation(annotation);
            this.updateAnnotationList();
            this.selectAnnotation(annotation);
        },
        
        createArrowAnnotation: function(e) {
            const rect = e.target.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            
            const annotation = {
                id: ++annotationCounter,
                type: 'arrow',
                startX: x,
                startY: y,
                endX: x + 50,
                endY: y - 30,
                color: '#00d4ff',
                strokeWidth: 2
            };
            
            annotations.push(annotation);
            this.renderAnnotation(annotation);
            this.updateAnnotationList();
            this.selectAnnotation(annotation);
        },
        
        renderAnnotation: function(annotation) {
            let overlay = document.getElementById('annotation-overlay');
            if (!overlay) {
                overlay = document.createElement('div');
                overlay.id = 'annotation-overlay';
                overlay.className = 'annotation-overlay';
                
                const canvas = document.querySelector('#dicom-canvas') || document.querySelector('canvas');
                if (canvas) {
                    canvas.parentNode.style.position = 'relative';
                    canvas.parentNode.appendChild(overlay);
                }
            }
            
            if (annotation.type === 'text') {
                this.renderTextAnnotation(annotation, overlay);
            } else if (annotation.type === 'arrow') {
                this.renderArrowAnnotation(annotation, overlay);
            }
        },
        
        renderTextAnnotation: function(annotation, overlay) {
            let element = document.getElementById(`annotation-${annotation.id}`);
            if (!element) {
                element = document.createElement('div');
                element.id = `annotation-${annotation.id}`;
                element.className = 'annotation-text';
                overlay.appendChild(element);
                
                // Double-click to edit
                element.addEventListener('dblclick', () => this.editAnnotation(annotation));
                element.addEventListener('mousedown', (e) => this.startDrag(e, annotation));
            }
            
            // Update properties
            element.style.left = annotation.x + 'px';
            element.style.top = annotation.y + 'px';
            element.style.fontSize = annotation.fontSize;
            element.style.color = annotation.color;
            element.style.width = annotation.width + 'px';
            element.style.height = annotation.height + 'px';
            
            if (annotation.hasBackground) {
                element.style.backgroundColor = annotation.backgroundColor;
            } else {
                element.style.backgroundColor = 'transparent';
            }
            
            element.textContent = annotation.text;
            
            // Add resize handle if selected
            if (selectedAnnotation && selectedAnnotation.id === annotation.id) {
                element.classList.add('selected');
                this.addResizeHandle(element, annotation);
            } else {
                element.classList.remove('selected');
                this.removeResizeHandle(element);
            }
        },
        
        renderArrowAnnotation: function(annotation, overlay) {
            let svg = overlay.querySelector('svg');
            if (!svg) {
                svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                svg.style.cssText = 'position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;';
                
                // Add arrowhead marker
                const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
                const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
                marker.setAttribute('id', 'arrowhead');
                marker.setAttribute('markerWidth', '10');
                marker.setAttribute('markerHeight', '7');
                marker.setAttribute('refX', '9');
                marker.setAttribute('refY', '3.5');
                marker.setAttribute('orient', 'auto');
                
                const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
                polygon.setAttribute('points', '0 0, 10 3.5, 0 7');
                polygon.setAttribute('fill', '#00d4ff');
                
                marker.appendChild(polygon);
                defs.appendChild(marker);
                svg.appendChild(defs);
                overlay.appendChild(svg);
            }
            
            let line = svg.querySelector(`#arrow-${annotation.id}`);
            if (!line) {
                line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                line.id = `arrow-${annotation.id}`;
                line.className = 'annotation-arrow';
                svg.appendChild(line);
                
                line.addEventListener('mousedown', (e) => this.startDrag(e, annotation));
            }
            
            line.setAttribute('x1', annotation.startX);
            line.setAttribute('y1', annotation.startY);
            line.setAttribute('x2', annotation.endX);
            line.setAttribute('y2', annotation.endY);
            line.setAttribute('stroke', annotation.color);
            line.setAttribute('stroke-width', annotation.strokeWidth);
        },
        
        addResizeHandle: function(element, annotation) {
            this.removeResizeHandle(element);
            
            const handle = document.createElement('div');
            handle.className = 'resize-handle bottom-right';
            element.appendChild(handle);
            
            handle.addEventListener('mousedown', (e) => {
                e.stopPropagation();
                this.startResize(e, annotation);
            });
        },
        
        removeResizeHandle: function(element) {
            const handle = element.querySelector('.resize-handle');
            if (handle) {
                handle.remove();
            }
        },
        
        startDrag: function(e, annotation) {
            if (currentTool !== 'select') return;
            
            e.preventDefault();
            e.stopPropagation();
            
            isDragging = true;
            selectedAnnotation = annotation;
            
            const rect = e.target.getBoundingClientRect();
            dragOffset.x = e.clientX - rect.left;
            dragOffset.y = e.clientY - rect.top;
            
            this.selectAnnotation(annotation);
        },
        
        startResize: function(e, annotation) {
            e.preventDefault();
            e.stopPropagation();
            
            isResizing = true;
            selectedAnnotation = annotation;
        },
        
        onMouseDown: function(e) {
            if (currentTool === 'select' && !e.target.closest('.annotation-text') && !e.target.closest('.annotation-arrow')) {
                this.deselectAll();
            }
        },
        
        onMouseMove: function(e) {
            if (isDragging && selectedAnnotation) {
                const rect = e.target.getBoundingClientRect();
                
                if (selectedAnnotation.type === 'text') {
                    selectedAnnotation.x = e.clientX - rect.left - dragOffset.x;
                    selectedAnnotation.y = e.clientY - rect.top - dragOffset.y;
                } else if (selectedAnnotation.type === 'arrow') {
                    const deltaX = e.clientX - rect.left - selectedAnnotation.startX;
                    const deltaY = e.clientY - rect.top - selectedAnnotation.startY;
                    
                    selectedAnnotation.startX += deltaX;
                    selectedAnnotation.startY += deltaY;
                    selectedAnnotation.endX += deltaX;
                    selectedAnnotation.endY += deltaY;
                }
                
                this.renderAnnotation(selectedAnnotation);
            } else if (isResizing && selectedAnnotation && selectedAnnotation.type === 'text') {
                const rect = e.target.getBoundingClientRect();
                selectedAnnotation.width = Math.max(50, e.clientX - rect.left - selectedAnnotation.x);
                selectedAnnotation.height = Math.max(20, e.clientY - rect.top - selectedAnnotation.y);
                
                this.renderAnnotation(selectedAnnotation);
            }
        },
        
        onMouseUp: function(e) {
            isDragging = false;
            isResizing = false;
        },
        
        onKeyDown: function(e) {
            if (e.key === 'Delete' && selectedAnnotation) {
                this.deleteAnnotation(selectedAnnotation.id);
            } else if (e.key === 'Escape') {
                this.deselectAll();
            }
        },
        
        editAnnotation: function(annotation) {
            if (annotation.type !== 'text') return;
            
            const element = document.getElementById(`annotation-${annotation.id}`);
            if (!element) return;
            
            element.classList.add('editing');
            element.contentEditable = true;
            element.focus();
            
            const range = document.createRange();
            range.selectNodeContents(element);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            
            element.addEventListener('blur', () => {
                element.classList.remove('editing');
                element.contentEditable = false;
                annotation.text = element.textContent;
            }, { once: true });
            
            element.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    element.blur();
                }
            });
        },
        
        selectAnnotation: function(annotation) {
            selectedAnnotation = annotation;
            this.updateAnnotationList();
            this.updatePropertyControls(annotation);
            this.renderAllAnnotations();
        },
        
        deselectAll: function() {
            selectedAnnotation = null;
            this.updateAnnotationList();
            this.renderAllAnnotations();
        },
        
        updatePropertyControls: function(annotation) {
            if (annotation.type === 'text') {
                document.getElementById('font-size-slider').value = parseInt(annotation.fontSize);
                document.getElementById('font-size-value').textContent = annotation.fontSize;
                document.getElementById('annotation-color').value = annotation.color;
                document.getElementById('annotation-background').checked = annotation.hasBackground;
                document.getElementById('background-color').value = annotation.backgroundColor;
                document.getElementById('background-color').disabled = !annotation.hasBackground;
            }
        },
        
        updateSelectedAnnotation: function(property, value) {
            if (!selectedAnnotation) return;
            
            selectedAnnotation[property] = value;
            this.renderAnnotation(selectedAnnotation);
        },
        
        updateAnnotationList: function() {
            const container = document.getElementById('annotations-container');
            if (!container) return;
            
            container.innerHTML = annotations.map(annotation => `
                <div class="annotation-item ${selectedAnnotation && selectedAnnotation.id === annotation.id ? 'selected' : ''}"
                     onclick="AnnotationSystem.selectAnnotationById(${annotation.id})">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span>${annotation.type === 'text' ? annotation.text.substring(0, 20) : 'Arrow'}</span>
                        <button onclick="event.stopPropagation(); AnnotationSystem.deleteAnnotation(${annotation.id})" 
                                style="background: none; border: none; color: #ff4444; cursor: pointer;">×</button>
                    </div>
                </div>
            `).join('');
        },
        
        selectAnnotationById: function(id) {
            const annotation = annotations.find(a => a.id === id);
            if (annotation) {
                this.selectAnnotation(annotation);
            }
        },
        
        deleteAnnotation: function(id) {
            annotations = annotations.filter(a => a.id !== id);
            
            const element = document.getElementById(`annotation-${id}`);
            if (element) element.remove();
            
            const arrow = document.querySelector(`#arrow-${id}`);
            if (arrow) arrow.remove();
            
            if (selectedAnnotation && selectedAnnotation.id === id) {
                selectedAnnotation = null;
            }
            
            this.updateAnnotationList();
        },
        
        clearAllAnnotations: function() {
            annotations = [];
            selectedAnnotation = null;
            annotationCounter = 0;
            
            const overlay = document.getElementById('annotation-overlay');
            if (overlay) {
                overlay.innerHTML = '';
            }
            
            this.updateAnnotationList();
        },
        
        renderAllAnnotations: function() {
            annotations.forEach(annotation => this.renderAnnotation(annotation));
        },
        
        exportAnnotations: function() {
            const data = {
                timestamp: new Date().toISOString(),
                patient_id: window.currentPatient?.id || 'Unknown',
                study_id: window.currentStudy?.id || 'Unknown',
                annotations: annotations
            };
            
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `annotations_${Date.now()}.json`;
            a.click();
            URL.revokeObjectURL(url);
        }
    };
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => AnnotationSystem.init());
    } else {
        AnnotationSystem.init();
    }
    
})();