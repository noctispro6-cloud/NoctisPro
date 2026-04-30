/**
 * Unified Button Handlers for NoctisPro PACS
 * Comprehensive button functionality with error handling and visual feedback
 */

class NoctisProButtonManager {
    constructor() {
        this.csrfToken = this.getCSRFToken();
        this.init();
    }

    init() {
        this.setupGlobalStyles();
        this.enhanceAllButtons();
        this.setupEventListeners();
        this.initializeToastSystem();
    }

    getCSRFToken() {
        const sources = [
            () => document.querySelector('[name=csrfmiddlewaretoken]')?.value,
            () => document.querySelector('meta[name=csrf-token]')?.getAttribute('content'),
            () => document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='))?.split('=')[1]
        ];
        
        for (let getToken of sources) {
            try {
                const token = getToken();
                if (token && token.trim()) return token.trim();
            } catch (e) { /* ignore */ }
        }
        
        return null;
    }

    setupGlobalStyles() {
        if (document.getElementById('noctispro-button-styles')) return;
        
        const style = document.createElement('style');
        style.id = 'noctispro-button-styles';
        style.textContent = `
            .noctispro-loading {
                position: relative;
                pointer-events: none;
                opacity: 0.7;
            }
            
            .noctispro-loading::after {
                content: '';
                position: absolute;
                top: 50%;
                left: 50%;
                width: 16px;
                height: 16px;
                margin: -8px 0 0 -8px;
                border: 2px solid transparent;
                border-top: 2px solid currentColor;
                border-radius: 50%;
                animation: noctispro-spin 1s linear infinite;
                z-index: 1;
            }
            
            @keyframes noctispro-spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            
            .noctispro-button-enhanced {
                transition: all 0.2s ease;
                position: relative;
                overflow: hidden;
            }
            
            .noctispro-button-enhanced:hover:not(:disabled) {
                transform: translateY(-1px);
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            }
            
            .noctispro-button-enhanced:active:not(:disabled) {
                transform: translateY(0);
            }
            
            .noctispro-ripple {
                position: absolute;
                border-radius: 50%;
                background: rgba(255, 255, 255, 0.3);
                pointer-events: none;
                transform: scale(0);
                animation: noctispro-ripple 0.6s ease-out;
            }
            
            @keyframes noctispro-ripple {
                to {
                    transform: scale(2);
                    opacity: 0;
                }
            }
            
            .noctispro-toast {
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
                transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                display: flex;
                align-items: center;
                gap: 8px;
            }
            
            .noctispro-toast.show {
                transform: translateX(0);
            }
            
            .noctispro-toast.error {
                border-left-color: var(--danger-color, #ff4444);
            }
            
            .noctispro-toast.success {
                border-left-color: var(--success-color, #00ff88);
            }
            
            .noctispro-toast.warning {
                border-left-color: var(--warning-color, #ffaa00);
            }
        `;
        document.head.appendChild(style);
    }

    enhanceAllButtons() {
        const buttons = document.querySelectorAll('button, .btn, .btn-control, .btn-viewer, .tool, a[onclick]');
        buttons.forEach(button => this.enhanceButton(button));
    }

    enhanceButton(button) {
        if (button.classList.contains('noctispro-button-enhanced')) return;
        
        button.classList.add('noctispro-button-enhanced');
        
        // Add click ripple effect with safe handler
        button.addEventListener('mousedown', (e) => {
            try {
                // Prefer built-in method if present
                if (typeof this.createRipple === 'function') {
                    this.createRipple(e);
                } else if (window.ProfessionalButtons && typeof window.ProfessionalButtons.createRipple === 'function') {
                    window.ProfessionalButtons.createRipple(e);
                }
            } catch (_) {}
        });
        
        // Wrap existing onclick handlers with error handling
        if (button.onclick) {
            const originalOnClick = button.onclick;
            button.onclick = (event) => {
                try {
                    return originalOnClick.call(button, event);
                } catch (error) {
                    console.error('Button click error:', error);
                    this.showToast(`Error: ${error.message}`, 'error');
                    return false;
                }
            };
        }
    }

    createRipple(e) {
        const button = e.currentTarget || e.target;
        if (!button || button.disabled) return;
        const rect = button.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const x = (e.clientX ?? (rect.left + rect.width / 2)) - rect.left - size / 2;
        const y = (e.clientY ?? (rect.top + rect.height / 2)) - rect.top - size / 2;
        const ripple = document.createElement('span');
        ripple.className = 'noctispro-ripple';
        ripple.style.cssText = `
            width: ${size}px;
            height: ${size}px;
            left: ${x}px;
            top: ${y}px;
        `;
        // Ensure container clips
        button.style.position = button.style.position || 'relative';
        button.style.overflow = 'hidden';
        button.appendChild(ripple);
        setTimeout(() => ripple.remove(), 600);
    }

    setupEventListeners() {
        // Add global error handler for button clicks
        document.addEventListener('click', (e) => {
            const button = e.target.closest('button, .btn, .tool');
            if (button && button.disabled) {
                e.preventDefault();
                e.stopPropagation();
                return false;
            }
        });
    }

    initializeToastSystem() {
        // Remove any existing toasts on page load
        document.querySelectorAll('.noctispro-toast').forEach(toast => toast.remove());
    }

    // Utility methods
    setButtonLoading(button, loading = true) {
        if (!button) return;
        
        if (loading) {
            button.classList.add('noctispro-loading');
            button.disabled = true;
            if (!button.dataset.originalText) {
                button.dataset.originalText = button.innerHTML;
            }
        } else {
            button.classList.remove('noctispro-loading');
            button.disabled = false;
            if (button.dataset.originalText) {
                button.innerHTML = button.dataset.originalText;
                delete button.dataset.originalText;
            }
        }
    }

    showToast(message, type = 'info', duration = 3000) {
        const toast = document.createElement('div');
        toast.className = `noctispro-toast ${type}`;
        
        const icon = this.getToastIcon(type);
        toast.innerHTML = `
            <i class="fas fa-${icon}"></i>
            <span>${message}</span>
        `;
        
        document.body.appendChild(toast);
        
        // Animate in
        setTimeout(() => toast.classList.add('show'), 10);
        
        // Auto-remove
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    getToastIcon(type) {
        const icons = {
            'success': 'check-circle',
            'error': 'exclamation-triangle',
            'warning': 'exclamation-circle',
            'info': 'info-circle'
        };
        return icons[type] || 'info-circle';
    }

    // API helper
    async apiRequest(url, options = {}) {
        const defaultOptions = {
            method: 'GET',
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            }
        };

        if (options.method && options.method !== 'GET') {
            if (this.csrfToken) {
                defaultOptions.headers['X-CSRFToken'] = this.csrfToken;
            }
        }

        const finalOptions = { ...defaultOptions, ...options };
        if (options.headers) {
            finalOptions.headers = { ...defaultOptions.headers, ...options.headers };
        }

        try {
            const response = await fetch(url, finalOptions);

            const contentType = response.headers.get('content-type') || '';
            let payload = null;
            try {
                if (contentType.includes('application/json')) {
                    payload = await response.json();
                } else {
                    payload = await response.text();
                }
            } catch (e) {
                // ignore parse errors; keep payload as null
            }

            if (!response.ok) {
                const detail = payload && typeof payload === 'object' ? (payload.error || JSON.stringify(payload)) : (payload || response.statusText);
                throw new Error(`HTTP ${response.status}: ${detail}`);
            }

            if (contentType.includes('application/json')) {
                return payload;
            }
            return { success: true, data: payload };
        } catch (error) {
            console.error('API request failed:', error);
            throw error;
        }
    }
}

// Global button functions for the application
class NoctisProActions {
    constructor(buttonManager) {
        this.buttonManager = buttonManager;
    }

    // Navigation functions
    launchDicomViewer() {
        try {
            this.buttonManager.showToast('Launching DICOM Viewer...', 'info');
            window.location.href = '/dicom-viewer/';
        } catch (error) {
            this.buttonManager.showToast('Failed to launch DICOM Viewer', 'error');
        }
    }

    loadFromDirectory() {
        try {
            this.buttonManager.showToast('Opening directory loader...', 'info');
            window.location.href = '/dicom-viewer/load-directory/';
        } catch (error) {
            this.buttonManager.showToast('Failed to open directory loader', 'error');
        }
    }

    uploadStudies() {
        try {
            window.location.href = '/worklist/upload/';
        } catch (error) {
            this.buttonManager.showToast('Failed to open upload page', 'error');
        }
    }

    // Data refresh functions
    async refreshData(buttonElement = null) {
        if (buttonElement) {
            this.buttonManager.setButtonLoading(buttonElement, true);
        }

        try {
            const data = await this.buttonManager.apiRequest('/worklist/api/refresh-worklist/');
            
            if (data.success !== false) {
                this.buttonManager.showToast('Data refreshed successfully', 'success');
                setTimeout(() => window.location.reload(), 1000);
            } else {
                throw new Error(data.error || 'Refresh failed');
            }
        } catch (error) {
            this.buttonManager.showToast(`Refresh failed: ${error.message}`, 'error');
        } finally {
            if (buttonElement) {
                this.buttonManager.setButtonLoading(buttonElement, false);
            }
        }
    }

    resetFilters() {
        try {
            const filterInputs = [
                'dateFilter', 'searchFilter', 'statusFilter', 
                'modalityFilter', 'priorityFilter'
            ];

            filterInputs.forEach(id => {
                const element = document.getElementById(id);
                if (element) {
                    element.value = '';
                }
            });

            // Set date to today
            const dateFilter = document.getElementById('dateFilter');
            if (dateFilter) {
                dateFilter.value = new Date().toISOString().split('T')[0];
            }

            this.buttonManager.showToast('Filters reset successfully', 'success');
            
            // Apply filters if function exists
            if (typeof applyFilters === 'function') {
                applyFilters();
            }
        } catch (error) {
            this.buttonManager.showToast('Failed to reset filters', 'error');
        }
    }

    // Study functions
    async openStudyInViewer(studyId, buttonElement = null) {
        if (buttonElement) {
            this.buttonManager.setButtonLoading(buttonElement, true);
        }

        try {
            // Check if study exists
            const data = await this.buttonManager.apiRequest(`/worklist/api/study/${studyId}/`);
            
            if (data.success !== false) {
                window.location.href = `/dicom-viewer/?study=${studyId}`;
            } else {
                throw new Error(data.error || 'Study not accessible');
            }
        } catch (error) {
            if (buttonElement) {
                this.buttonManager.setButtonLoading(buttonElement, false);
            }
            this.buttonManager.showToast(`Failed to open study: ${error.message}`, 'error');
        }
    }

    async deleteStudy(studyId, accessionNumber, buttonElement = null) {
        const confirmed = confirm(
            `Are you sure you want to delete study ${accessionNumber}?\n\n` +
            `This action cannot be undone and will permanently remove all data.`
        );

        if (!confirmed) return;

        if (buttonElement) {
            this.buttonManager.setButtonLoading(buttonElement, true);
        }

        try {
            // Prefer POST first for broader proxy compatibility
            const postData = await this.buttonManager.apiRequest(`/worklist/api/study/${studyId}/delete/`, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });

            if (postData && postData.success !== false) {
                this.buttonManager.showToast(`Study ${accessionNumber} deleted successfully`, 'success');
                setTimeout(() => window.location.reload(), 1000);
                return;
            }
            throw new Error((postData && postData.error) || 'Failed to delete study');
        } catch (postError) {
            // Fallback to DELETE only if POST not allowed
            const msg = String(postError && postError.message || '');
            if (/HTTP\s*405|method not allowed/i.test(msg)) {
                try {
                    const delData = await this.buttonManager.apiRequest(`/worklist/api/study/${studyId}/delete/`, {
                        method: 'DELETE',
                    });
                    if (delData && delData.success !== false) {
                        this.buttonManager.showToast(`Study ${accessionNumber} deleted successfully`, 'success');
                        setTimeout(() => window.location.reload(), 1000);
                        return;
                    }
                    throw new Error((delData && delData.error) || 'Failed to delete study');
                } catch (delError) {
                    if (buttonElement) {
                        this.buttonManager.setButtonLoading(buttonElement, false);
                    }
                    this.buttonManager.showToast(`Delete failed: ${delError.message}`, 'error');
                    return;
                }
            }
            if (buttonElement) {
                this.buttonManager.setButtonLoading(buttonElement, false);
            }
            this.buttonManager.showToast(`Delete failed: ${postError.message}`, 'error');
        }
    }

    openReport(studyId) {
        try {
            window.location.href = `/reports/write/${studyId}/`;
        } catch (error) {
            this.buttonManager.showToast('Failed to open report', 'error');
        }
    }

    printStudy(studyId) {
        try {
            window.open(`/reports/print/${studyId}/`, '_blank');
        } catch (error) {
            this.buttonManager.showToast('Failed to open print dialog', 'error');
        }
    }

    // DICOM Viewer functions
    setTool(toolName) {
        try {
            // Update active tool
            document.querySelectorAll('.tool').forEach(tool => {
                tool.classList.remove('active');
            });
            
            const activeTool = document.querySelector(`[data-tool="${toolName}"]`);
            if (activeTool) {
                activeTool.classList.add('active');
            }

            // Set the active tool (this would connect to the actual viewer)
            if (typeof cornerstone !== 'undefined' && window.currentElement) {
                cornerstoneTools.setToolActive(toolName, { mouseButtonMask: 1 }, window.currentElement);
            }

            this.buttonManager.showToast(`${toolName.toUpperCase()} tool activated`, 'info', 1500);
        } catch (error) {
            this.buttonManager.showToast(`Failed to set ${toolName} tool`, 'error');
        }
    }

    resetView() {
        try {
            if (typeof cornerstone !== 'undefined' && window.currentElement) {
                cornerstone.reset(window.currentElement);
                this.buttonManager.showToast('View reset', 'success', 1500);
            } else {
                this.buttonManager.showToast('View reset (no image loaded)', 'info', 1500);
            }
        } catch (error) {
            this.buttonManager.showToast('Failed to reset view', 'error');
        }
    }

    // File operations
    loadFromLocalFiles() {
        try {
            const input = document.createElement('input');
            input.type = 'file';
            input.multiple = true;
            input.accept = '.dcm,.dicom';
            
            input.onchange = (e) => {
                const files = Array.from(e.target.files);
                if (files.length > 0) {
                    this.buttonManager.showToast(`Loading ${files.length} DICOM file(s)...`, 'info');
                    // Handle file loading here
                }
            };
            
            input.click();
        } catch (error) {
            this.buttonManager.showToast('Failed to open file dialog', 'error');
        }
    }

    exportImage() {
        try {
            if (typeof cornerstone !== 'undefined' && window.currentElement) {
                const canvas = cornerstone.getEnabledElement(window.currentElement).canvas;
                const link = document.createElement('a');
                link.download = `dicom-export-${Date.now()}.png`;
                link.href = canvas.toDataURL();
                link.click();
                this.buttonManager.showToast('Image exported successfully', 'success');
            } else {
                this.buttonManager.showToast('No image to export', 'warning');
            }
        } catch (error) {
            this.buttonManager.showToast('Failed to export image', 'error');
        }
    }
}

// Initialize the system
let noctisProButtonManager;
let noctisProActions;

document.addEventListener('DOMContentLoaded', function() {
    noctisProButtonManager = new NoctisProButtonManager();
    noctisProActions = new NoctisProActions(noctisProButtonManager);
    
    // Make functions globally available
    window.noctisProButtonManager = noctisProButtonManager;
    window.noctisProActions = noctisProActions;
    
    // Global function aliases for backward compatibility.
    // IMPORTANT: Do not override viewer pages that already define these functions
    // (e.g. the DICOM viewer templates implement their own rendering pipeline).
    const defineIfMissing = (name, fn) => {
        try {
            if (typeof window[name] !== 'function') {
                window[name] = fn;
            }
        } catch (_) { /* ignore */ }
    };

    defineIfMissing('launchDicomViewer', () => noctisProActions.launchDicomViewer());
    defineIfMissing('loadFromDirectory', () => noctisProActions.loadFromDirectory());
    defineIfMissing('uploadStudies', () => noctisProActions.uploadStudies());
    defineIfMissing('refreshData', (event) => {
        const button = event?.target?.closest('button');
        return noctisProActions.refreshData(button);
    });
    defineIfMissing('resetFilters', () => noctisProActions.resetFilters());
    defineIfMissing('openStudyInViewer', (studyId, event) => {
        const button = event?.target?.closest('button, a');
        return noctisProActions.openStudyInViewer(studyId, button);
    });
    defineIfMissing('deleteStudy', (studyId, accessionNumber, event) => {
        const button = event?.target?.closest('button');
        return noctisProActions.deleteStudy(studyId, accessionNumber, button);
    });
    defineIfMissing('openReport', (studyId) => noctisProActions.openReport(studyId));
    defineIfMissing('printStudy', (studyId) => noctisProActions.printStudy(studyId));
    defineIfMissing('setTool', (toolName) => noctisProActions.setTool(toolName));
    defineIfMissing('resetView', () => noctisProActions.resetView());
    defineIfMissing('loadFromLocalFiles', () => noctisProActions.loadFromLocalFiles());
    defineIfMissing('exportImage', () => noctisProActions.exportImage());
    
    // Re-enhance buttons when new content is added
    const observer = new MutationObserver((mutations) => {
        let shouldReinitialize = false;
        mutations.forEach((mutation) => {
            mutation.addedNodes.forEach((node) => {
                if (node.nodeType === Node.ELEMENT_NODE) {
                    if (node.tagName === 'BUTTON' || node.classList?.contains('btn') || 
                        node.querySelector?.('button, .btn')) {
                        shouldReinitialize = true;
                    }
                }
            });
        });
        
        if (shouldReinitialize) {
            setTimeout(() => noctisProButtonManager.enhanceAllButtons(), 100);
        }
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
});

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { NoctisProButtonManager, NoctisProActions };
}