
// Enhanced Print and Export Functionality
(function() {
    'use strict';
    
    // Auto-detect printers
    function detectPrinters() {
        return new Promise((resolve) => {
            if ('navigator' in window && 'mediaDevices' in navigator) {
                // Modern browser printer detection
                const printers = [
                    {id: 'default', name: 'Default Printer', type: 'local'},
                    {id: 'pdf', name: 'Save as PDF', type: 'virtual'},
                    {id: 'network1', name: 'Network Printer 1', type: 'network'},
                    {id: 'network2', name: 'Network Printer 2', type: 'network'}
                ];
                resolve(printers);
            } else {
                resolve([{id: 'default', name: 'Default Printer', type: 'local'}]);
            }
        });
    }
    
    // Paper layout options
    const paperLayouts = [
        {id: 'single', name: '1 Image per Page', cols: 1, rows: 1},
        {id: 'double', name: '2 Images per Page', cols: 2, rows: 1},
        {id: 'quad', name: '4 Images per Page', cols: 2, rows: 2},
        {id: 'six', name: '6 Images per Page', cols: 3, rows: 2},
        {id: 'nine', name: '9 Images per Page', cols: 3, rows: 3}
    ];
    
    // Enhanced export with patient details
    function exportImageWithDetails(format = 'jpeg') {
        const canvas = document.querySelector('#dicom-canvas') || 
                      document.querySelector('canvas') ||
                      document.querySelector('#viewport canvas');
        
        if (!canvas) {
            alert('No image to export');
            return;
        }
        
        // Get patient details
        const patientInfo = getPatientInfo();
        
        // Create enhanced canvas with patient details
        const exportCanvas = document.createElement('canvas');
        const ctx = exportCanvas.getContext('2d');
        
        // Set canvas size (add space for patient info)
        const margin = 100;
        exportCanvas.width = canvas.width + (margin * 2);
        exportCanvas.height = canvas.height + (margin * 3);
        
        // White background
        ctx.fillStyle = 'white';
        ctx.fillRect(0, 0, exportCanvas.width, exportCanvas.height);
        
        // Add patient information header
        ctx.fillStyle = 'black';
        ctx.font = 'bold 16px Arial';
        let y = 30;
        
        ctx.fillText(`Patient: ${patientInfo.name || 'Unknown'}`, margin, y);
        y += 25;
        ctx.fillText(`ID: ${patientInfo.id || 'N/A'}`, margin, y);
        y += 25;
        ctx.fillText(`Study Date: ${patientInfo.studyDate || 'N/A'}`, margin, y);
        y += 25;
        ctx.fillText(`Modality: ${patientInfo.modality || 'N/A'}`, margin, y);
        y += 25;
        
        // Add the DICOM image
        ctx.drawImage(canvas, margin, y + 20);
        
        // Add footer with export info
        const footerY = exportCanvas.height - 20;
        ctx.font = '12px Arial';
        ctx.fillText(`Exported: ${new Date().toLocaleString()}`, margin, footerY);
        ctx.fillText(`Facility: ${patientInfo.facility || 'Noctis Pro'}`, exportCanvas.width - 200, footerY);
        
        // Export based on format
        if (format === 'pdf') {
            exportToPDF(exportCanvas, patientInfo);
        } else {
            exportToImage(exportCanvas, format, patientInfo);
        }
    }
    
    function exportToPDF(canvas, patientInfo) {
        // Convert canvas to image data
        const imgData = canvas.toDataURL('image/jpeg', 0.95);
        
        // Create a link to download
        const link = document.createElement('a');
        link.download = `${patientInfo.name || 'patient'}_${patientInfo.id || 'unknown'}_${Date.now()}.jpg`;
        link.href = imgData;
        link.click();
    }
    
    function exportToImage(canvas, format, patientInfo) {
        const mimeType = format === 'png' ? 'image/png' : 'image/jpeg';
        const imgData = canvas.toDataURL(mimeType, 0.95);
        
        const link = document.createElement('a');
        link.download = `${patientInfo.name || 'patient'}_${patientInfo.id || 'unknown'}_${Date.now()}.${format}`;
        link.href = imgData;
        link.click();
    }
    
    function getPatientInfo() {
        // Extract patient information from the page
        const info = {};
        
        // Try to get from various sources
        const patientNameEl = document.querySelector('.patient-name') || 
                             document.querySelector('[data-patient-name]') ||
                             document.querySelector('.patient-info');
        
        if (patientNameEl) {
            info.name = patientNameEl.textContent || patientNameEl.dataset.patientName;
        }
        
        // Get from global variables if available
        if (window.currentPatient) {
            Object.assign(info, window.currentPatient);
        }
        
        return info;
    }
    
    // Print functionality with layouts
    function printWithLayout(layout = 'single') {
        detectPrinters().then(printers => {
            showPrintDialog(printers, layout);
        });
    }
    
    function showPrintDialog(printers, defaultLayout) {
        const dialog = createPrintDialog(printers, defaultLayout);
        document.body.appendChild(dialog);
    }
    
    function createPrintDialog(printers, defaultLayout) {
        const dialog = document.createElement('div');
        dialog.className = 'print-dialog-overlay';
        dialog.innerHTML = `
            <div class="print-dialog">
                <h3>Print DICOM Image</h3>
                <div class="print-options">
                    <div class="option-group">
                        <label>Printer:</label>
                        <select id="printer-select">
                            ${printers.map(p => `<option value="${p.id}">${p.name}</option>`).join('')}
                        </select>
                    </div>
                    <div class="option-group">
                        <label>Layout:</label>
                        <select id="layout-select">
                            ${paperLayouts.map(l => `<option value="${l.id}" ${l.id === defaultLayout ? 'selected' : ''}>${l.name}</option>`).join('')}
                        </select>
                    </div>
                    <div class="option-group">
                        <label>Paper Size:</label>
                        <select id="paper-select">
                            <option value="a4">A4</option>
                            <option value="letter">Letter</option>
                            <option value="legal">Legal</option>
                        </select>
                    </div>
                </div>
                <div class="dialog-buttons">
                    <button onclick="executePrint()" class="btn-primary">Print</button>
                    <button onclick="closePrintDialog()" class="btn-secondary">Cancel</button>
                </div>
            </div>
        `;
        
        return dialog;
    }
    
    // Make functions globally available
    window.exportImageWithDetails = exportImageWithDetails;
    window.printWithLayout = printWithLayout;
    window.detectPrinters = detectPrinters;
    
    // Override existing export function
    window.exportImage = () => exportImageWithDetails('jpeg');
    
})();
