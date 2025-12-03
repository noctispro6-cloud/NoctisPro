
// DICOM Loading Fix
(function() {
    'use strict';
    
    // Enhanced DICOM loading with better error handling
    window.loadDicomImageEnhanced = async function(imageId, seriesId) {
        try {
            // Show loading indicator
            showLoadingIndicator();
            
            // Clear previous error states
            clearErrorMessages();
            
            // Make request with proper headers
            const response = await fetch(`/dicom-viewer/api/image/${imageId}/`, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'Cache-Control': 'no-cache'
                },
                credentials: 'same-origin'
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: Failed to load DICOM image`);
            }
            
            const data = await response.json();
            
            if (data.error) {
                throw new Error(data.error);
            }
            
            // Update image display
            if (data.image_data) {
                updateImageDisplay(data);
                updateImageInfo(data);
            } else {
                throw new Error('No image data received');
            }
            
        } catch (error) {
            console.error('DICOM loading error:', error);
            showErrorMessage(`Failed to load DICOM image: ${error.message}`);
        } finally {
            hideLoadingIndicator();
        }
    };
    
    function showLoadingIndicator() {
        const indicator = document.getElementById('loading-indicator') || createLoadingIndicator();
        indicator.style.display = 'block';
    }
    
    function hideLoadingIndicator() {
        const indicator = document.getElementById('loading-indicator');
        if (indicator) {
            indicator.style.display = 'none';
        }
    }
    
    function createLoadingIndicator() {
        const indicator = document.createElement('div');
        indicator.id = 'loading-indicator';
        indicator.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading DICOM...';
        indicator.style.cssText = `
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 20px;
            border-radius: 8px;
            z-index: 10000;
            display: none;
        `;
        document.body.appendChild(indicator);
        return indicator;
    }
    
    function showErrorMessage(message) {
        const errorDiv = document.getElementById('error-message') || createErrorDiv();
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
        
        // Auto-hide after 5 seconds
        setTimeout(() => {
            errorDiv.style.display = 'none';
        }, 5000);
    }
    
    function clearErrorMessages() {
        const errorDiv = document.getElementById('error-message');
        if (errorDiv) {
            errorDiv.style.display = 'none';
        }
    }
    
    function createErrorDiv() {
        const errorDiv = document.createElement('div');
        errorDiv.id = 'error-message';
        errorDiv.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #ff4444;
            color: white;
            padding: 15px;
            border-radius: 8px;
            z-index: 10000;
            display: none;
            max-width: 400px;
        `;
        document.body.appendChild(errorDiv);
        return errorDiv;
    }
    
    // Override existing loading functions
    if (typeof loadDicomImage !== 'undefined') {
        window.loadDicomImage = window.loadDicomImageEnhanced;
    }
    
})();
