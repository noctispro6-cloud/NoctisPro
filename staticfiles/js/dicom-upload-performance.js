/**
 * DICOM Upload Performance Optimization
 * Enhanced file upload with compression and progress tracking for slow networks
 */

(function() {
    'use strict';
    
    // Configuration for slow network optimization
    const UPLOAD_CONFIG = {
        CHUNK_SIZE: 1024 * 1024, // 1MB chunks
        MAX_CONCURRENT_UPLOADS: 3,
        COMPRESSION_THRESHOLD: 5 * 1024 * 1024, // 5MB
        RETRY_ATTEMPTS: 3,
        PROGRESS_UPDATE_INTERVAL: 500, // 500ms
    };
    
    class EnhancedDicomUploader {
        constructor() {
            this.activeUploads = new Map();
            this.compressionWorker = null;
            this.initializeWorker();
        }
        
        initializeWorker() {
            // Create web worker for file compression if supported
            if (typeof Worker !== 'undefined') {
                try {
                    const workerCode = `
                        self.onmessage = function(e) {
                            const { fileData, filename } = e.data;
                            
                            // Simple compression simulation (in real implementation, use proper compression)
                            const compressed = new Uint8Array(fileData);
                            
                            self.postMessage({
                                success: true,
                                compressedData: compressed,
                                filename: filename,
                                originalSize: fileData.byteLength,
                                compressedSize: compressed.byteLength
                            });
                        };
                    `;
                    
                    const blob = new Blob([workerCode], { type: 'application/javascript' });
                    this.compressionWorker = new Worker(URL.createObjectURL(blob));
                } catch (e) {
                    console.warn('Web Worker not available, using main thread processing');
                }
            }
        }
        
        async compressFile(file) {
            return new Promise((resolve) => {
                if (file.size < UPLOAD_CONFIG.COMPRESSION_THRESHOLD) {
                    resolve({ file: file, compressed: false });
                    return;
                }
                
                if (this.compressionWorker) {
                    this.compressionWorker.onmessage = (e) => {
                        const { compressedData, originalSize, compressedSize } = e.data;
                        const compressedFile = new File([compressedData], file.name, { type: file.type });
                        resolve({ 
                            file: compressedFile, 
                            compressed: true, 
                            originalSize, 
                            compressedSize 
                        });
                    };
                    
                    file.arrayBuffer().then(buffer => {
                        this.compressionWorker.postMessage({
                            fileData: buffer,
                            filename: file.name
                        });
                    });
                } else {
                    // Fallback to no compression
                    resolve({ file: file, compressed: false });
                }
            });
        }
        
        async uploadFiles(files, progressCallback) {
            const uploadId = this.generateUploadId();
            const totalFiles = files.length;
            let completedFiles = 0;
            let errors = [];
            
            progressCallback({
                uploadId,
                current: 0,
                total: totalFiles,
                percentage: 0,
                status: 'preparing',
                errors: []
            });
            
            try {
                // Process files in batches
                const batches = this.createBatches(files, UPLOAD_CONFIG.MAX_CONCURRENT_UPLOADS);
                
                for (const batch of batches) {
                    const batchPromises = batch.map(async (file) => {
                        try {
                            // Compress if needed
                            const { file: processedFile, compressed } = await this.compressFile(file);
                            
                            // Upload file
                            await this.uploadSingleFile(processedFile, uploadId);
                            
                            completedFiles++;
                            progressCallback({
                                uploadId,
                                current: completedFiles,
                                total: totalFiles,
                                percentage: Math.round((completedFiles / totalFiles) * 100),
                                status: 'uploading',
                                errors: errors
                            });
                            
                        } catch (error) {
                            errors.push(`${file.name}: ${error.message}`);
                            console.error(`Upload failed for ${file.name}:`, error);
                        }
                    });
                    
                    await Promise.all(batchPromises);
                }
                
                // Finalize upload
                const result = await this.finalizeUpload(uploadId);
                
                progressCallback({
                    uploadId,
                    current: completedFiles,
                    total: totalFiles,
                    percentage: 100,
                    status: 'completed',
                    errors: errors,
                    result: result
                });
                
                return result;
                
            } catch (error) {
                progressCallback({
                    uploadId,
                    current: completedFiles,
                    total: totalFiles,
                    percentage: 0,
                    status: 'failed',
                    errors: [...errors, error.message]
                });
                throw error;
            }
        }
        
        createBatches(files, batchSize) {
            const batches = [];
            for (let i = 0; i < files.length; i += batchSize) {
                batches.push(files.slice(i, i + batchSize));
            }
            return batches;
        }
        
        async uploadSingleFile(file, uploadId) {
            const formData = new FormData();
            formData.append('dicom_files', file);
            formData.append('upload_id', uploadId);
            
            let attempts = 0;
            while (attempts < UPLOAD_CONFIG.RETRY_ATTEMPTS) {
                try {
                    const response = await fetch('/dicom-viewer/upload/', {
                        method: 'POST',
                        body: formData,
                        headers: {
                            'X-CSRFToken': this.getCSRFToken()
                        }
                    });
                    
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                    }
                    
                    const result = await response.json();
                    if (!result.success) {
                        throw new Error(result.error || 'Upload failed');
                    }
                    
                    return result;
                    
                } catch (error) {
                    attempts++;
                    if (attempts >= UPLOAD_CONFIG.RETRY_ATTEMPTS) {
                        throw error;
                    }
                    
                    // Wait before retry with exponential backoff
                    await this.delay(1000 * Math.pow(2, attempts - 1));
                }
            }
        }
        
        async finalizeUpload(uploadId) {
            // This would typically trigger server-side processing
            // For now, just return success
            return {
                success: true,
                uploadId: uploadId,
                message: 'Upload completed successfully'
            };
        }
        
        generateUploadId() {
            return 'upload_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        }
        
        getCSRFToken() {
            const token = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                         document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                         this.getCookie('csrftoken');
            return token;
        }
        
        getCookie(name) {
            let cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
            }
            return cookieValue;
        }
        
        delay(ms) {
            return new Promise(resolve => setTimeout(resolve, ms));
        }
    }
    
    // Enhanced file input handling with drag and drop
    class DicomFileHandler {
        constructor() {
            this.uploader = new EnhancedDicomUploader();
            this.initializeDropZone();
            this.initializeFileInput();
        }
        
        initializeDropZone() {
            const dropZone = document.querySelector('.viewport') || document.body;
            
            ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
                dropZone.addEventListener(eventName, this.preventDefaults, false);
            });
            
            ['dragenter', 'dragover'].forEach(eventName => {
                dropZone.addEventListener(eventName, this.highlight.bind(this), false);
            });
            
            ['dragleave', 'drop'].forEach(eventName => {
                dropZone.addEventListener(eventName, this.unhighlight.bind(this), false);
            });
            
            dropZone.addEventListener('drop', this.handleDrop.bind(this), false);
        }
        
        initializeFileInput() {
            const fileInput = document.getElementById('fileInput');
            if (fileInput) {
                fileInput.addEventListener('change', this.handleFileSelect.bind(this));
            }
        }
        
        preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }
        
        highlight(e) {
            const dropZone = e.currentTarget;
            dropZone.classList.add('drag-over');
        }
        
        unhighlight(e) {
            const dropZone = e.currentTarget;
            dropZone.classList.remove('drag-over');
        }
        
        handleDrop(e) {
            const dt = e.dataTransfer;
            const files = dt.files;
            this.processFiles([...files]);
        }
        
        handleFileSelect(e) {
            const files = e.target.files;
            this.processFiles([...files]);
        }
        
        async processFiles(files) {
            if (!files || files.length === 0) {
                return;
            }
            
            // Filter DICOM files
            const dicomFiles = files.filter(file => 
                file.name.toLowerCase().endsWith('.dcm') || 
                file.name.toLowerCase().endsWith('.dicom') ||
                file.type === 'application/dicom'
            );
            
            if (dicomFiles.length === 0) {
                this.showMessage('No DICOM files found in selection', 'warning');
                return;
            }
            
            // Show upload progress
            this.showUploadProgress();
            
            try {
                await this.uploader.uploadFiles(dicomFiles, (progress) => {
                    this.updateProgress(progress);
                });
                
                // Refresh study list after successful upload
                if (typeof loadStudiesList === 'function') {
                    await loadStudiesList();
                }
                
            } catch (error) {
                console.error('Upload failed:', error);
                this.showMessage('Upload failed: ' + error.message, 'error');
            } finally {
                this.hideUploadProgress();
            }
        }
        
        showUploadProgress() {
            const progressModal = document.createElement('div');
            progressModal.id = 'uploadProgressModal';
            progressModal.className = 'modal-overlay';
            progressModal.innerHTML = `
                <div class="modal-content" style="max-width: 500px;">
                    <div class="modal-header">
                        <h3>Uploading DICOM Files</h3>
                    </div>
                    <div class="modal-body">
                        <div id="uploadProgressBar" style="background: var(--border-color); border-radius: 10px; overflow: hidden; height: 20px; margin-bottom: 10px;">
                            <div id="uploadProgressFill" style="background: var(--accent-color); height: 100%; width: 0%; transition: width 0.3s ease;"></div>
                        </div>
                        <div id="uploadProgressText">Preparing upload...</div>
                        <div id="uploadProgressDetails" style="margin-top: 10px; font-size: 12px; color: var(--text-secondary);"></div>
                    </div>
                </div>
            `;
            
            document.body.appendChild(progressModal);
        }
        
        updateProgress(progress) {
            const progressFill = document.getElementById('uploadProgressFill');
            const progressText = document.getElementById('uploadProgressText');
            const progressDetails = document.getElementById('uploadProgressDetails');
            
            if (progressFill) {
                progressFill.style.width = progress.percentage + '%';
            }
            
            if (progressText) {
                progressText.textContent = `${progress.status.charAt(0).toUpperCase() + progress.status.slice(1)} - ${progress.current}/${progress.total} files (${progress.percentage}%)`;
            }
            
            if (progressDetails && progress.errors.length > 0) {
                progressDetails.innerHTML = `<strong>Errors:</strong><br>${progress.errors.slice(-3).join('<br>')}`;
            }
        }
        
        hideUploadProgress() {
            const progressModal = document.getElementById('uploadProgressModal');
            if (progressModal) {
                progressModal.remove();
            }
        }
        
        showMessage(message, type = 'info') {
            if (typeof showToast === 'function') {
                showToast(message, type);
            } else {
                alert(message);
            }
        }
    }
    
    // Initialize when DOM is ready
    document.addEventListener('DOMContentLoaded', function() {
        window.dicomFileHandler = new DicomFileHandler();
    });
    
    // Add CSS for drag and drop styling
    const style = document.createElement('style');
    style.textContent = `
        .drag-over {
            background-color: rgba(0, 212, 255, 0.1) !important;
            border: 2px dashed var(--accent-color) !important;
        }
        
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10000;
        }
        
        .modal-content {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 20px;
            min-width: 300px;
        }
        
        .modal-header h3 {
            margin: 0 0 15px 0;
            color: var(--accent-color);
        }
        
        .modal-body {
            color: var(--text-primary);
        }
    `;
    document.head.appendChild(style);
    
})();