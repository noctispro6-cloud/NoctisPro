/**
 * High-Quality Medical Image Renderer
 * Professional-grade image rendering for DICOM medical images
 * Optimized for DX, CR, MG, CT, MR, US, and other modalities
 */

class HighQualityImageRenderer {
    constructor() {
        this.dpr = window.devicePixelRatio || 1;
        this.canvas = null;
        this.ctx = null;
        this.imageCache = new Map();
        this.renderingOptions = {
            antialiasing: true,
            sharpening: true,
            contrastEnhancement: true,
            noiseReduction: true
        };
    }

    /**
     * Initialize canvas with high-quality settings
     */
    initializeCanvas(canvasElement) {
        this.canvas = canvasElement;
        this.ctx = this.canvas.getContext('2d');
        
        // Enable high-quality rendering
        this.ctx.imageSmoothingEnabled = true;
        this.ctx.imageSmoothingQuality = 'high';
        
        return this;
    }

    /**
     * Render medical image with modality-specific optimizations
     */
    renderMedicalImage(imageElement, modality = '', options = {}) {
        if (!this.canvas || !this.ctx || !imageElement.complete) {
            return false;
        }

        const mergedOptions = { ...this.renderingOptions, ...options };
        
        // Get display dimensions
        const rect = this.canvas.getBoundingClientRect();
        const displayWidth = rect.width;
        const displayHeight = rect.height;
        
        // Set canvas size for high-DPI displays
        this.canvas.width = displayWidth * this.dpr;
        this.canvas.height = displayHeight * this.dpr;
        
        // Scale canvas back down using CSS
        this.canvas.style.width = displayWidth + 'px';
        this.canvas.style.height = displayHeight + 'px';
        
        // Scale drawing context
        this.ctx.scale(this.dpr, this.dpr);
        
        // Apply modality-specific rendering settings
        this.applyModalitySettings(modality, mergedOptions);
        
        // Calculate aspect-preserving dimensions
        const imgAspect = imageElement.naturalWidth / imageElement.naturalHeight;
        const canvasAspect = displayWidth / displayHeight;
        
        let drawWidth, drawHeight, drawX, drawY;
        
        if (imgAspect > canvasAspect) {
            drawWidth = displayWidth;
            drawHeight = displayWidth / imgAspect;
            drawX = 0;
            drawY = (displayHeight - drawHeight) / 2;
        } else {
            drawWidth = displayHeight * imgAspect;
            drawHeight = displayHeight;
            drawX = (displayWidth - drawWidth) / 2;
            drawY = 0;
        }
        
        // Clear canvas
        this.ctx.fillStyle = '#000000';
        this.ctx.fillRect(0, 0, displayWidth, displayHeight);
        
        // Apply transforms if available
        if (typeof zoomFactor !== 'undefined' && typeof panX !== 'undefined' && typeof panY !== 'undefined') {
            this.ctx.save();
            this.ctx.translate(displayWidth / 2, displayHeight / 2);
            this.ctx.scale(zoomFactor, zoomFactor);
            this.ctx.translate(-displayWidth / 2 + panX / zoomFactor, -displayHeight / 2 + panY / zoomFactor);
        }
        
        // Render image with high quality
        this.ctx.drawImage(imageElement, drawX, drawY, drawWidth, drawHeight);
        
        if (typeof zoomFactor !== 'undefined') {
            this.ctx.restore();
        }
        
        // Skip post-processing to prevent white image issue
        // Post-processing disabled to maintain medical image integrity
        
        return true;
    }

    /**
     * Apply modality-specific rendering settings
     */
    applyModalitySettings(modality, options) {
        const upperModality = modality.toUpperCase();
        
        // Configure rendering based on modality
        switch (upperModality) {
            case 'DX':
            case 'CR':
            case 'MG':
                // Digital Radiography, Computed Radiography, Mammography
                this.ctx.filter = 'contrast(1.2) brightness(1.1) saturate(0.9)';
                break;
            case 'CT':
                // Computed Tomography
                this.ctx.filter = 'contrast(1.15) brightness(1.08)';
                break;
            case 'MR':
            case 'MRI':
                // Magnetic Resonance
                this.ctx.filter = 'contrast(1.18) brightness(1.05) saturate(1.1)';
                break;
            case 'US':
                // Ultrasound
                this.ctx.filter = 'contrast(1.25) brightness(1.12)';
                break;
            case 'XA':
            case 'RF':
                // X-Ray Angiography, Radiofluoroscopy
                this.ctx.filter = 'contrast(1.3) brightness(1.15)';
                break;
            default:
                // Default medical imaging enhancement
                this.ctx.filter = 'contrast(1.15) brightness(1.08)';
        }
    }

    /**
     * Apply post-processing effects for enhanced image quality
     */
    applyPostProcessing(modality, options) {
        if (!options.contrastEnhancement && !options.sharpening) return;
        
        try {
            const imageData = this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height);
            const data = imageData.data;
            
            if (options.contrastEnhancement) {
                // Apply histogram equalization-like enhancement
                this.enhanceContrast(data, modality);
            }
            
            if (options.sharpening) {
                // Apply unsharp mask
                this.applySharpeningFilter(data, imageData.width, imageData.height);
            }
            
            this.ctx.putImageData(imageData, 0, 0);
        } catch (error) {
            console.warn('Post-processing failed:', error);
        }
    }

    /**
     * Enhance contrast using adaptive histogram equalization
     */
    enhanceContrast(data, modality) {
        const histogram = new Array(256).fill(0);
        const pixelCount = data.length / 4;
        
        // Build histogram
        for (let i = 0; i < data.length; i += 4) {
            const gray = Math.round(0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]);
            histogram[gray]++;
        }
        
        // Calculate cumulative distribution
        const cdf = new Array(256);
        cdf[0] = histogram[0];
        for (let i = 1; i < 256; i++) {
            cdf[i] = cdf[i - 1] + histogram[i];
        }
        
        // Normalize CDF
        const cdfMin = cdf.find(val => val > 0);
        const factor = 255 / (pixelCount - cdfMin);
        
        // Apply enhancement with modality-specific strength
        let strength = 0.3; // Default
        switch (modality.toUpperCase()) {
            case 'DX':
            case 'CR':
            case 'MG':
                strength = 0.4; // Stronger for radiography
                break;
            case 'CT':
                strength = 0.25; // Moderate for CT
                break;
            case 'MR':
            case 'MRI':
                strength = 0.35; // Good for MR
                break;
            case 'US':
                strength = 0.5; // Strong for ultrasound
                break;
        }
        
        for (let i = 0; i < data.length; i += 4) {
            const gray = Math.round(0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]);
            const enhanced = Math.round((cdf[gray] - cdfMin) * factor);
            const blended = Math.round(gray * (1 - strength) + enhanced * strength);
            
            data[i] = data[i + 1] = data[i + 2] = Math.max(0, Math.min(255, blended));
        }
    }

    /**
     * Apply sharpening filter using unsharp mask
     */
    applySharpeningFilter(data, width, height) {
        const kernel = [
            0, -1, 0,
            -1, 5, -1,
            0, -1, 0
        ];
        
        const output = new Uint8ClampedArray(data.length);
        
        for (let y = 1; y < height - 1; y++) {
            for (let x = 1; x < width - 1; x++) {
                const idx = (y * width + x) * 4;
                
                let r = 0, g = 0, b = 0;
                
                for (let ky = -1; ky <= 1; ky++) {
                    for (let kx = -1; kx <= 1; kx++) {
                        const kidx = ((y + ky) * width + (x + kx)) * 4;
                        const weight = kernel[(ky + 1) * 3 + (kx + 1)];
                        
                        r += data[kidx] * weight;
                        g += data[kidx + 1] * weight;
                        b += data[kidx + 2] * weight;
                    }
                }
                
                output[idx] = Math.max(0, Math.min(255, r));
                output[idx + 1] = Math.max(0, Math.min(255, g));
                output[idx + 2] = Math.max(0, Math.min(255, b));
                output[idx + 3] = data[idx + 3]; // Alpha
            }
        }
        
        // Copy processed data back
        for (let i = 0; i < data.length; i++) {
            data[i] = output[i];
        }
    }

    /**
     * Set rendering quality options
     */
    setQualityOptions(options) {
        this.renderingOptions = { ...this.renderingOptions, ...options };
        return this;
    }

    /**
     * Clear canvas
     */
    clear() {
        if (this.ctx) {
            this.ctx.fillStyle = '#000000';
            this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
        }
        return this;
    }
}

// Global instance for use in DICOM viewer
window.HighQualityRenderer = new HighQualityImageRenderer();

// Enhanced render function for medical images
window.renderImageToCanvas = function(imgElement, canvas, modality = '') {
    if (!window.HighQualityRenderer.canvas) {
        window.HighQualityRenderer.initializeCanvas(canvas);
    }
    
    return window.HighQualityRenderer.renderMedicalImage(imgElement, modality, {
        antialiasing: true,
        sharpening: false, // Disabled to prevent white image issue
        contrastEnhancement: false, // Disabled to prevent white image issue
        noiseReduction: false // Keep false to preserve medical data integrity
    });
};

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        const canvas = document.getElementById('dicomCanvas');
        if (canvas) {
            window.HighQualityRenderer.initializeCanvas(canvas);
        }
    });
} else {
    const canvas = document.getElementById('dicomCanvas');
    if (canvas) {
        window.HighQualityRenderer.initializeCanvas(canvas);
    }
}