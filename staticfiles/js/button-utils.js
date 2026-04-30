/**
 * Professional Button Utilities for Noctis Pro PACS
 * Enhanced interaction handling and visual feedback
 */

// Professional button enhancement system
class ProfessionalButtons {
    constructor() {
        this.init();
    }

    init() {
        this.enhanceAllButtons();
        this.setupGlobalEventListeners();
    }

    enhanceAllButtons() {
        // Enhance all buttons with professional interactions
        const buttons = document.querySelectorAll('button, .btn, .btn-control, .btn-viewer, .tool');
        
        buttons.forEach(button => {
            this.enhanceButton(button);
        });
    }

    enhanceButton(button) {
        // Add professional hover and click effects
        button.addEventListener('mouseenter', this.handleButtonHover.bind(this));
        button.addEventListener('mouseleave', this.handleButtonLeave.bind(this));
        button.addEventListener('mousedown', this.handleButtonPress.bind(this));
        button.addEventListener('mouseup', this.handleButtonRelease.bind(this));
        
        // Enable ripple containment
        button.style.position = 'relative';
        button.style.overflow = 'hidden';
    }

    handleButtonHover(e) {
        if (e.target.disabled) return;
        
        e.target.style.transform = 'translateY(-1px)';
        e.target.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.2)';
    }

    handleButtonLeave(e) {
        if (e.target.disabled) return;
        
        e.target.style.transform = '';
        e.target.style.boxShadow = '';
    }

    handleButtonPress(e) {
        const btn = e.currentTarget || e.target;
        if (btn && btn.disabled) return;

        // Trigger ripple with safe static method
        ProfessionalButtons.createRipple(e);

        if (btn) {
            btn.style.transform = 'translateY(0)';
        }
    }

    handleButtonRelease(e) {
        if (e.target.disabled) return;
        
        setTimeout(() => {
            e.target.style.transform = 'translateY(-1px)';
        }, 100);
    }

    // Robust static ripple to avoid context issues
    static createRipple(e) {
        const button = (e && (e.currentTarget || e.target)) || null;
        if (!button) return;
        if (button.disabled) return;
        const rect = button.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const x = (e.clientX ?? (rect.left + rect.width / 2)) - rect.left - size / 2;
        const y = (e.clientY ?? (rect.top + rect.height / 2)) - rect.top - size / 2;
        const ripple = document.createElement('span');
        ripple.style.cssText = `
            position: absolute;
            width: ${size}px;
            height: ${size}px;
            left: ${x}px;
            top: ${y}px;
            background: rgba(255, 255, 255, 0.3);
            border-radius: 50%;
            transform: scale(0);
            animation: ripple 0.6s ease-out;
            pointer-events: none;
        `;
        button.appendChild(ripple);
        setTimeout(() => ripple.remove(), 600);
    }

    

    setupGlobalEventListeners() {
        // Add CSS for ripple animation
        if (!document.getElementById('professional-button-styles')) {
            const style = document.createElement('style');
            style.id = 'professional-button-styles';
            style.textContent = `
                @keyframes ripple {
                    to {
                        transform: scale(2);
                        opacity: 0;
                    }
                }
                
                .btn-loading {
                    pointer-events: none;
                    opacity: 0.7;
                }
                
                .btn-loading::after {
                    content: '';
                    position: absolute;
                    width: 16px;
                    height: 16px;
                    margin: auto;
                    border: 2px solid transparent;
                    border-top-color: currentColor;
                    border-radius: 50%;
                    animation: spin 1s linear infinite;
                }
                
                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
            `;
            document.head.appendChild(style);
        }
    }

    // Utility methods for button states
    static setLoading(button, loading = true) {
        if (loading) {
            button.classList.add('btn-loading');
            button.disabled = true;
            button.dataset.originalText = button.textContent;
            button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
        } else {
            button.classList.remove('btn-loading');
            button.disabled = false;
            if (button.dataset.originalText) {
                button.textContent = button.dataset.originalText;
                delete button.dataset.originalText;
            }
        }
    }

    static setSuccess(button, message = 'Success', duration = 2000) {
        const originalBg = button.style.background;
        const originalColor = button.style.color;
        const originalText = button.textContent;
        
        button.style.background = 'var(--success-color)';
        button.style.color = 'var(--primary-bg)';
        button.innerHTML = '<i class="fas fa-check"></i> ' + message;
        
        setTimeout(() => {
            button.style.background = originalBg;
            button.style.color = originalColor;
            button.textContent = originalText;
        }, duration);
    }

    static setError(button, message = 'Error', duration = 2000) {
        const originalBg = button.style.background;
        const originalColor = button.style.color;
        const originalText = button.textContent;
        
        button.style.background = 'var(--danger-color)';
        button.style.color = 'var(--text-primary)';
        button.innerHTML = '<i class="fas fa-exclamation-triangle"></i> ' + message;
        
        setTimeout(() => {
            button.style.background = originalBg;
            button.style.color = originalColor;
            button.textContent = originalText;
        }, duration);
    }
}

// Professional toast notification system
class ProfessionalToast {
    static show(message, type = 'info', duration = 3000) {
        const toast = document.createElement('div');
        toast.className = `professional-toast toast-${type}`;
        
        const icon = this.getIcon(type);
        toast.innerHTML = `
            <div class="toast-content">
                <i class="fas fa-${icon}"></i>
                <span>${message}</span>
            </div>
            <button class="toast-close" onclick="this.parentElement.remove()">
                <i class="fas fa-times"></i>
            </button>
        `;
        
        // Add styles if not already present
        this.addToastStyles();
        
        document.body.appendChild(toast);
        
        // Animate in
        setTimeout(() => toast.classList.add('show'), 10);
        
        // Auto-remove
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    static getIcon(type) {
        const icons = {
            'success': 'check-circle',
            'error': 'exclamation-triangle',
            'warning': 'exclamation-circle',
            'info': 'info-circle'
        };
        return icons[type] || 'info-circle';
    }

    static addToastStyles() {
        if (document.getElementById('professional-toast-styles')) return;
        
        const style = document.createElement('style');
        style.id = 'professional-toast-styles';
        style.textContent = `
            .professional-toast {
                position: fixed;
                top: 20px;
                right: 20px;
                background: var(--card-surface);
                border: 1px solid var(--border-color);
                border-left: 4px solid var(--accent-color);
                color: var(--text-primary);
                padding: 12px 16px;
                border-radius: 8px;
                box-shadow: 0 8px 25px rgba(0, 0, 0, 0.3);
                z-index: 2000;
                font-size: 12px;
                max-width: 350px;
                transform: translateX(100%);
                transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
            }
            
            .professional-toast.show {
                transform: translateX(0);
            }
            
            .professional-toast.toast-error {
                border-left-color: var(--danger-color);
            }
            
            .professional-toast.toast-success {
                border-left-color: var(--success-color);
            }
            
            .professional-toast.toast-warning {
                border-left-color: var(--warning-color);
            }
            
            .toast-content {
                display: flex;
                align-items: center;
                gap: 8px;
                flex: 1;
            }
            
            .toast-close {
                background: none;
                border: none;
                color: var(--text-muted);
                cursor: pointer;
                padding: 4px;
                border-radius: 4px;
                transition: all 0.2s ease;
            }
            
            .toast-close:hover {
                background: var(--border-color);
                color: var(--text-primary);
            }
        `;
        document.head.appendChild(style);
    }
}

// Professional loading overlay system
class ProfessionalLoading {
    static show(message = 'Loading...', container = document.body) {
        const overlay = document.createElement('div');
        overlay.className = 'professional-loading-overlay';
        overlay.innerHTML = `
            <div class="loading-content">
                <div class="loading-spinner-professional"></div>
                <div class="loading-message">${message}</div>
            </div>
        `;
        
        this.addLoadingStyles();
        container.appendChild(overlay);
        
        setTimeout(() => overlay.classList.add('show'), 10);
        
        return overlay;
    }

    static hide(overlay) {
        if (overlay) {
            overlay.classList.remove('show');
            setTimeout(() => overlay.remove(), 300);
        }
    }

    static addLoadingStyles() {
        if (document.getElementById('professional-loading-styles')) return;
        
        const style = document.createElement('style');
        style.id = 'professional-loading-styles';
        style.textContent = `
            .professional-loading-overlay {
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.8);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 1000;
                opacity: 0;
                transition: opacity 0.3s ease;
            }
            
            .professional-loading-overlay.show {
                opacity: 1;
            }
            
            .loading-content {
                text-align: center;
                color: var(--text-primary);
            }
            
            .loading-spinner-professional {
                width: 40px;
                height: 40px;
                border: 3px solid rgba(0, 212, 255, 0.3);
                border-top: 3px solid var(--accent-color);
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin: 0 auto 16px;
            }
            
            .loading-message {
                font-size: 14px;
                font-weight: 500;
            }
        `;
        document.head.appendChild(style);
    }
}

// Professional form validation
class ProfessionalValidation {
    static validateForm(form) {
        const inputs = form.querySelectorAll('input[required], select[required], textarea[required]');
        let isValid = true;
        
        inputs.forEach(input => {
            if (!this.validateInput(input)) {
                isValid = false;
            }
        });
        
        return isValid;
    }

    static validateInput(input) {
        const value = input.value.trim();
        const isValid = value.length > 0;
        
        input.classList.toggle('is-invalid', !isValid);
        input.classList.toggle('is-valid', isValid);
        
        return isValid;
    }

    static addValidationStyles() {
        if (document.getElementById('professional-validation-styles')) return;
        
        const style = document.createElement('style');
        style.id = 'professional-validation-styles';
        style.textContent = `
            .is-invalid {
                border-color: var(--danger-color) !important;
                box-shadow: 0 0 0 2px rgba(255, 68, 68, 0.2) !important;
            }
            
            .is-valid {
                border-color: var(--success-color) !important;
                box-shadow: 0 0 0 2px rgba(0, 255, 136, 0.2) !important;
            }
        `;
        document.head.appendChild(style);
    }
}

// Initialize professional enhancements when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Initialize professional button system
    new ProfessionalButtons();
    
    // Add validation styles
    ProfessionalValidation.addValidationStyles();
    
    // Enhance forms with real-time validation
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        const inputs = form.querySelectorAll('input, select, textarea');
        inputs.forEach(input => {
            input.addEventListener('blur', () => ProfessionalValidation.validateInput(input));
        });
    });
});

// Global utility functions
window.ProfessionalButtons = ProfessionalButtons;
window.ProfessionalToast = ProfessionalToast;
window.ProfessionalLoading = ProfessionalLoading;
window.ProfessionalValidation = ProfessionalValidation;