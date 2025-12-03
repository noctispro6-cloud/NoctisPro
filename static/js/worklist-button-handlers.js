/**
 * Comprehensive Worklist Button Handlers
 * Handles all button functionality in worklist templates with proper error handling
 */

window.WorklistUtils = {
    
    // CSRF token helper
    getCSRFToken: function() {
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
    
    // Toast notification system
    showToast: function(message, type = 'info', duration = 3000) {
        const toast = document.createElement('div');
        toast.className = `worklist-toast worklist-toast-${type}`;
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
    
    // API request helper with error handling
    apiRequest: async function(url, options = {}) {
        const defaultOptions = {
            method: 'GET',
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            }
        };
        
        // Add CSRF token for non-GET requests
        if (options.method && options.method !== 'GET') {
            const csrfToken = this.getCSRFToken();
            if (csrfToken) {
                defaultOptions.headers['X-CSRFToken'] = csrfToken;
            }
        }
        
        const finalOptions = { ...defaultOptions, ...options };
        if (options.headers) {
            finalOptions.headers = { ...defaultOptions.headers, ...options.headers };
        }
        
        try {
            const response = await fetch(url, finalOptions);
            
            if (!response.ok) {
                if (response.status === 500) {
                    throw new Error(`Server error (500): ${url}`);
                } else if (response.status === 403) {
                    throw new Error('Permission denied');
                } else if (response.status === 404) {
                    throw new Error('Endpoint not found');
                } else {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
            }
            
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return await response.json();
            } else {
                return { success: true, data: await response.text() };
            }
            
        } catch (error) {
            console.error('API request failed:', error);
            throw error;
        }
    },
    
    // Worklist button handlers
    refreshData: async function(buttonElement = null) {
        if (buttonElement) {
            this.setButtonLoading(buttonElement, true);
        }
        
        try {
            const data = await this.apiRequest('/worklist/api/refresh-worklist/');
            
            if (data.success) {
                // Reload the page to refresh data
                window.location.reload();
            } else {
                throw new Error(data.error || 'Failed to refresh');
            }
            
        } catch (error) {
            this.showToast(`Refresh failed: ${error.message}`, 'error');
        } finally {
            if (buttonElement) {
                this.setButtonLoading(buttonElement, false);
            }
        }
    },
    
    resetFilters: function() {
        // Reset all filter inputs
        const inputs = [
            'dateFilter', 'searchFilter', 'statusFilter', 
            'modalityFilter', 'priorityFilter'
        ];
        
        inputs.forEach(id => {
            const element = document.getElementById(id);
            if (element) {
                element.value = '';
            }
        });
        
        // Set date to today if date filter exists
        const dateFilter = document.getElementById('dateFilter');
        if (dateFilter) {
            const today = new Date().toISOString().split('T')[0];
            dateFilter.value = today;
        }
        
        this.showToast('Filters reset', 'success');
    },
    
    uploadStudies: function() {
        window.location.href = '/worklist/upload/';
    },
    
    openStudyInViewer: async function(studyId, buttonElement = null) {
        if (buttonElement) {
            this.setButtonLoading(buttonElement, true);
        }
        
        try {
            // Check if study exists and user has permission
            const data = await this.apiRequest(`/worklist/api/study/${studyId}/`);
            
            if (data.success) {
                // Open in DICOM viewer
                window.location.href = `/dicom-viewer/?study=${studyId}`;
            } else {
                throw new Error(data.error || 'Study not accessible');
            }
            
        } catch (error) {
            if (buttonElement) {
                this.setButtonLoading(buttonElement, false);
            }
            this.showToast(`Failed to open study: ${error.message}`, 'error');
        }
    },
    
    deleteStudy: async function(studyId, accessionNumber, buttonElement = null) {
        // Confirm deletion
        const confirmed = confirm(
            `Are you sure you want to delete study ${accessionNumber}?\n\n` +
            `This action cannot be undone and will permanently remove:\n` +
            `• DICOM images\n• Series data\n• Reports\n• Measurements\n• Annotations`
        );
        
        if (!confirmed) return;
        
        if (buttonElement) {
            this.setButtonLoading(buttonElement, true);
        }
        
        try {
            const data = await this.apiRequest(`/worklist/api/study/${studyId}/delete/`, {
                method: 'DELETE'
            });
            
            if (data.success) {
                this.showToast(`Study ${accessionNumber} deleted successfully`, 'success');
                // Reload page to refresh list
                setTimeout(() => window.location.reload(), 1000);
            } else {
                throw new Error(data.error || 'Failed to delete study');
            }
            
        } catch (error) {
            if (buttonElement) {
                this.setButtonLoading(buttonElement, false);
            }
            this.showToast(`Delete failed: ${error.message}`, 'error');
        }
    },
    
    openReport: function(studyId) {
        window.location.href = `/reports/write/${studyId}/`;
    },
    
    printStudy: function(studyId) {
        window.open(`/reports/print/${studyId}/`, '_blank');
    },
    
    redirectToDashboard: function() {
        window.location.href = '/worklist/';
    },
    
    // Clinical info update
    updateClinicalInfo: async function(studyId, clinicalInfo, buttonElement = null) {
        if (buttonElement) {
            this.setButtonLoading(buttonElement, true);
        }
        
        try {
            const data = await this.apiRequest(`/worklist/api/study/${studyId}/update-clinical-info/`, {
                method: 'POST',
                body: JSON.stringify({ clinical_info: clinicalInfo })
            });
            
            if (data.success) {
                this.showToast('Clinical information updated', 'success');
                return true;
            } else {
                throw new Error(data.error || 'Failed to update');
            }
            
        } catch (error) {
            this.showToast(`Update failed: ${error.message}`, 'error');
            return false;
        } finally {
            if (buttonElement) {
                this.setButtonLoading(buttonElement, false);
            }
        }
    },
    
    // Initialize all worklist buttons
    initializeButtons: function() {
        // Add error handling to all buttons
        document.querySelectorAll('button, a').forEach(element => {
            if (!element.hasAttribute('data-worklist-initialized')) {
                element.setAttribute('data-worklist-initialized', 'true');
                
                // Add error boundary for onclick handlers
                const originalOnclick = element.onclick;
                if (originalOnclick) {
                    element.onclick = function(event) {
                        try {
                            return originalOnclick.call(this, event);
                        } catch (error) {
                            console.error('Button click error:', error);
                            WorklistUtils.showToast(`Button error: ${error.message}`, 'error');
                            return false;
                        }
                    };
                }
            }
        });
    }
};

// Global convenience functions for backward compatibility
window.refreshData = function(event) {
    const button = event ? event.target.closest('button') : null;
    return WorklistUtils.refreshData(button);
};

window.resetFilters = function() {
    return WorklistUtils.resetFilters();
};

window.uploadStudies = function() {
    return WorklistUtils.uploadStudies();
};

window.openStudyInViewer = function(studyId, event = null) {
    const button = event ? event.target.closest('button, a') : null;
    return WorklistUtils.openStudyInViewer(studyId, button);
};

window.deleteStudy = function(studyId, accessionNumber, event = null) {
    const button = event ? event.target.closest('button') : null;
    return WorklistUtils.deleteStudy(studyId, accessionNumber, button);
};

window.openReport = function(studyId) {
    return WorklistUtils.openReport(studyId);
};

window.printStudy = function(studyId) {
    return WorklistUtils.printStudy(studyId);
};

window.redirectToDashboard = function() {
    return WorklistUtils.redirectToDashboard();
};

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => WorklistUtils.initializeButtons());
} else {
    WorklistUtils.initializeButtons();
}

// Re-initialize buttons when new content is added dynamically
const observer = new MutationObserver((mutations) => {
    let shouldReinitialize = false;
    mutations.forEach((mutation) => {
        mutation.addedNodes.forEach((node) => {
            if (node.nodeType === Node.ELEMENT_NODE) {
                if (node.tagName === 'BUTTON' || node.tagName === 'A' || 
                    node.querySelector?.('button, a')) {
                    shouldReinitialize = true;
                }
            }
        });
    });
    
    if (shouldReinitialize) {
        WorklistUtils.initializeButtons();
    }
});

observer.observe(document.body, {
    childList: true,
    subtree: true
});

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = WorklistUtils;
}