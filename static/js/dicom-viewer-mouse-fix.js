
// Enhanced DICOM Viewer Mouse Controls Fix
(function() {
    'use strict';
    
    let mouseControlsEnabled = false;
    let currentTool = 'window';
    let isMouseDown = false;
    let lastMousePos = {x: 0, y: 0};
    
    // Fix mouse controls to only work when tool is selected and mouse is pressed
    function initializeMouseControls() {
        const imageContainer = document.getElementById('dicom-image-container') || 
                              document.querySelector('.image-container') ||
                              document.querySelector('#viewport');
        
        if (!imageContainer) {
            console.warn('DICOM image container not found');
            return;
        }
        
        // Remove existing event listeners to prevent conflicts
        imageContainer.removeEventListener('mousemove', handleMouseMove);
        imageContainer.removeEventListener('mousedown', handleMouseDown);
        imageContainer.removeEventListener('mouseup', handleMouseUp);
        imageContainer.removeEventListener('wheel', handleMouseWheel);
        
        // Add fixed event listeners
        imageContainer.addEventListener('mousedown', handleMouseDown);
        imageContainer.addEventListener('mousemove', handleMouseMove);
        imageContainer.addEventListener('mouseup', handleMouseUp);
        imageContainer.addEventListener('wheel', handleMouseWheel, {passive: false});
        
        // Keyboard controls for slice navigation
        document.addEventListener('keydown', handleKeyDown);
        
        console.log('✅ Mouse controls initialized');
    }
    
    function handleMouseDown(e) {
        if (e.button === 0) { // Left click only
            isMouseDown = true;
            lastMousePos = {x: e.clientX, y: e.clientY};
            e.preventDefault();
        }
    }
    
    function handleMouseMove(e) {
        // Only apply windowing if mouse is pressed AND window tool is active
        if (isMouseDown && currentTool === 'window') {
            const deltaX = e.clientX - lastMousePos.x;
            const deltaY = e.clientY - lastMousePos.y;
            
            if (typeof handleWindowing === 'function') {
                handleWindowing(deltaX, deltaY);
            }
            
            lastMousePos = {x: e.clientX, y: e.clientY};
        }
        
        // Update HU values on mouse move (without changing window/level)
        if (typeof updateHUValue === 'function') {
            updateHUValue(e);
        }
    }
    
    function handleMouseUp(e) {
        if (e.button === 0) {
            isMouseDown = false;
        }
    }
    
    function handleMouseWheel(e) {
        e.preventDefault();
        
        // Slice navigation with mouse wheel
        if (typeof navigateSlice === 'function') {
            const direction = e.deltaY > 0 ? 1 : -1;
            navigateSlice(direction);
        }
    }
    
    function handleKeyDown(e) {
        // Keyboard slice navigation
        if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
            e.preventDefault();
            if (typeof navigateSlice === 'function') {
                const direction = e.key === 'ArrowUp' ? -1 : 1;
                navigateSlice(direction);
            }
        }
    }
    
    // Tool selection fix
    function setTool(tool) {
        currentTool = tool;
        
        // Update UI to show active tool
        document.querySelectorAll('.tool').forEach(btn => {
            btn.classList.remove('active');
        });
        
        const activeBtn = document.querySelector(`[data-tool="${tool}"]`);
        if (activeBtn) {
            activeBtn.classList.add('active');
        }
        
        console.log('Tool changed to:', tool);
    }
    
    // Make functions globally available
    window.setTool = setTool;
    window.initializeMouseControls = initializeMouseControls;
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeMouseControls);
    } else {
        initializeMouseControls();
    }
    
})();
