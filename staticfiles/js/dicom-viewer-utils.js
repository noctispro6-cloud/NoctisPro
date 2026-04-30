/**
 * Standardized DICOM Viewer Button Utilities
 * Professional medical-grade JavaScript utilities for consistent DICOM viewer functionality
 */

// Global DICOM viewer utilities
window.DicomViewerUtils = {
    
    // Base URL for DICOM viewer
    baseUrl: '/dicom-viewer/',
    
    // Error handling and user feedback
    showToast: function(message, type = 'info', duration = 3000) {
        const toast = document.createElement('div');
        toast.className = `dicom-toast dicom-toast-${type}`;
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: var(--card-bg, #252525);
            border: 1px solid var(--border-color, #404040);
            border-left: 4px solid var(--accent-color, #00d4ff);
            color: var(--text-primary, #ffffff);
            padding: 12px 16px;
            border-radius: 6px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            z-index: 10000;
            font-size: 12px;
            max-width: 350px;
            transform: translateX(100%);
            transition: transform 0.3s ease;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        `;
        
        // Type-specific styling
        if (type === 'error') {
            toast.style.borderLeftColor = 'var(--danger-color, #ff4444)';
        } else if (type === 'success') {
            toast.style.borderLeftColor = 'var(--success-color, #00ff88)';
        } else if (type === 'warning') {
            toast.style.borderLeftColor = 'var(--warning-color, #ffaa00)';
        }
        
        const icon = type === 'success' ? 'check' : type === 'error' ? 'exclamation-triangle' : 'info-circle';
        toast.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px;">
                <i class="fas fa-${icon}"></i>
                <span>${message}</span>
            </div>
        `;
        
        document.body.appendChild(toast);
        
        // Slide in
        setTimeout(() => toast.style.transform = 'translateX(0)', 10);
        
        // Auto-remove
        setTimeout(() => {
            toast.style.transform = 'translateX(100%)';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    },
    
    // Button state management
    setButtonLoading: function(button, isLoading = true) {
        if (!button) return;
        
        if (isLoading) {
            button.classList.add('loading');
            button.disabled = true;
            button.setAttribute('data-original-text', button.innerHTML);
            button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
        } else {
            button.classList.remove('loading');
            button.disabled = false;
            const originalText = button.getAttribute('data-original-text');
            if (originalText) {
                button.innerHTML = originalText;
                button.removeAttribute('data-original-text');
            }
        }
    },
    
    // CSRF token helper
    getCSRFToken: function() {
        // Try multiple sources for CSRF token
        const sources = [
            () => document.querySelector('[name=csrfmiddlewaretoken]')?.value,
            () => document.querySelector('meta[name=csrf-token]')?.getAttribute('content'),
            () => {
                const cookies = document.cookie.split(';');
                for (let cookie of cookies) {
                    const [name, value] = cookie.trim().split('=');
                    if (name === 'csrftoken') return value;
                }
                return null;
            }
        ];
        
        for (let getToken of sources) {
            const token = getToken();
            if (token && token.trim()) return token.trim();
        }
        
        return null;
    },
    
    // Study launching functions
    openStudyInViewer: async function(studyId, buttonElement = null) {
        if (buttonElement) {
            this.setButtonLoading(buttonElement, true);
        }
        
        try {
            // Validate study access
            const response = await fetch(`/worklist/api/study/${studyId}/`);
            if (!response.ok) {
                throw new Error('Study not found or access denied');
            }
            
            // Open in DICOM viewer
            const url = `${this.baseUrl}?study=${studyId}`;
            window.location.href = url;
            
        } catch (error) {
            if (buttonElement) {
                this.setButtonLoading(buttonElement, false);
            }
            console.error('Error opening DICOM viewer:', error);
            this.showToast(`Failed to open DICOM viewer: ${error.message}`, 'error');
        }
    },
    
    // Launch standalone viewer
    launchDicomViewer: function(buttonElement = null) {
        if (buttonElement) {
            this.setButtonLoading(buttonElement, true);
        }
        
        try {
            window.location.href = this.baseUrl;
        } catch (error) {
            if (buttonElement) {
                this.setButtonLoading(buttonElement, false);
            }
            console.error('Error launching DICOM viewer:', error);
            this.showToast('Failed to launch DICOM viewer', 'error');
        }
    },
    
    // Enhanced button click handlers
    handleViewerButtonClick: function(action, studyId = null, event = null) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        
        const button = event ? event.target.closest('button, a') : null;
        
        switch (action) {
            case 'open_study':
                if (studyId) {
                    this.openStudyInViewer(studyId, button);
                } else {
                    this.showToast('No study ID provided', 'error');
                }
                break;
                
            case 'launch_viewer':
                this.launchDicomViewer(button);
                break;
                
            case 'open_in_new_tab':
                if (studyId) {
                    const url = `${this.baseUrl}?study=${studyId}`;
                    window.open(url, '_blank');
                } else {
                    window.open(this.baseUrl, '_blank');
                }
                break;
                
            default:
                this.showToast('Unknown action', 'error');
        }
    },
    
    // Initialize all DICOM viewer buttons on page load
    initializeButtons: function() {
        // Add click handlers to all DICOM viewer buttons
        document.querySelectorAll('.btn-dicom-viewer').forEach(button => {
            if (!button.hasAttribute('data-initialized')) {
                button.setAttribute('data-initialized', 'true');
                
                // Add ripple effect
                button.addEventListener('click', function(e) {
                    const ripple = document.createElement('span');
                    const rect = button.getBoundingClientRect();
                    const size = Math.max(rect.width, rect.height);
                    const x = e.clientX - rect.left - size / 2;
                    const y = e.clientY - rect.top - size / 2;
                    
                    ripple.style.cssText = `
                        position: absolute;
                        width: ${size}px;
                        height: ${size}px;
                        left: ${x}px;
                        top: ${y}px;
                        background: rgba(255, 255, 255, 0.3);
                        border-radius: 50%;
                        transform: scale(0);
                        animation: ripple 0.6s linear;
                        pointer-events: none;
                    `;
                    
                    button.style.position = 'relative';
                    button.style.overflow = 'hidden';
                    button.appendChild(ripple);
                    
                    setTimeout(() => ripple.remove(), 600);
                });
            }
        });
        
        // Add CSS for ripple animation if not already added
        if (!document.getElementById('dicom-ripple-styles')) {
            const style = document.createElement('style');
            style.id = 'dicom-ripple-styles';
            style.textContent = `
                @keyframes ripple {
                    to {
                        transform: scale(2);
                        opacity: 0;
                    }
                }
            `;
            document.head.appendChild(style);
        }
    },
    
    // Validate DICOM viewer availability
    checkViewerAvailability: async function() {
        try {
            const response = await fetch(`${this.baseUrl}api/health/`, {
                method: 'HEAD',
                credentials: 'same-origin'
            });
            return response.ok;
        } catch (error) {
            return false;
        }
    },
    
    // Utility function to handle errors gracefully
    handleError: function(error, context = 'DICOM Viewer') {
        console.error(`${context} error:`, error);
        this.showToast(`${context}: ${error.message || 'Unknown error'}`, 'error');
    }
};

// Global convenience functions for backward compatibility
window.openStudyInViewer = function(studyId, event = null) {
    return DicomViewerUtils.handleViewerButtonClick('open_study', studyId, event);
};

window.launchDicomViewer = function(event = null) {
    return DicomViewerUtils.handleViewerButtonClick('launch_viewer', null, event);
};

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => DicomViewerUtils.initializeButtons());
} else {
    DicomViewerUtils.initializeButtons();
}

// Re-initialize buttons when new content is added dynamically
const observer = new MutationObserver((mutations) => {
    let shouldReinitialize = false;
    mutations.forEach((mutation) => {
        mutation.addedNodes.forEach((node) => {
            if (node.nodeType === Node.ELEMENT_NODE) {
                if (node.classList?.contains('btn-dicom-viewer') || 
                    node.querySelector?.('.btn-dicom-viewer')) {
                    shouldReinitialize = true;
                }
            }
        });
    });
    
    if (shouldReinitialize) {
        DicomViewerUtils.initializeButtons();
    }
});

observer.observe(document.body, {
    childList: true,
    subtree: true
});

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DicomViewerUtils;
}