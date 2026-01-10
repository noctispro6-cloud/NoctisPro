
// Enhanced DICOM Viewer Mouse Controls Fix
(function() {
    'use strict';
    
    let mouseControlsEnabled = false;
    let currentTool = 'window';
    let isMouseDown = false;
    let lastMousePos = {x: 0, y: 0};
    let _wrappedSetTool = false;
    
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
        // If the main viewer is currently in MPR mode, don't try to apply single-view tools.
        try {
            if (typeof window._isMprVisible === 'function' && window._isMprVisible()) {
                return;
            }
        } catch (_) {}

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

        // If the main viewer is currently in MPR mode, single-view slice navigation should not run.
        try {
            if (typeof window._isMprVisible === 'function' && window._isMprVisible()) {
                return;
            }
        } catch (_) {}
        
        // Slice navigation with mouse wheel
        if (typeof navigateSlice === 'function') {
            const direction = e.deltaY > 0 ? 1 : -1;
            navigateSlice(direction);
        }
    }
    
    function handleKeyDown(e) {
        // If another handler already consumed this event, don't duplicate actions.
        if (e.defaultPrevented) return;

        // Don't trigger navigation while user is typing.
        const ae = document.activeElement;
        const tag = (ae && ae.tagName) ? ae.tagName.toUpperCase() : '';
        const isTyping = (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (ae && ae.isContentEditable));
        if (isTyping) return;

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
    
    // Make functions globally available WITHOUT clobbering the viewer's own implementations.
    // If the page already defines setTool (the main viewer does), wrap it so our local
    // state stays in sync while preserving the original behavior.
    try {
        const existingSetTool = window.setTool;
        if (typeof existingSetTool === 'function') {
            if (!existingSetTool.__noctis_mouse_fix_wrapped) {
                const wrapped = function(tool) {
                    try { currentTool = tool; } catch (_) {}
                    return existingSetTool.call(this, tool);
                };
                wrapped.__noctis_mouse_fix_wrapped = true;
                window.setTool = wrapped;
                _wrappedSetTool = true;
            }
        } else {
            window.setTool = setTool;
        }
    } catch (_) {
        // As a last resort, define if possible.
        try { if (typeof window.setTool !== 'function') window.setTool = setTool; } catch (_) {}
    }

    window.initializeMouseControls = initializeMouseControls;
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeMouseControls);
    } else {
        initializeMouseControls();
    }
    
})();
