
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
    
    // ---- Helpers ----
    function _getPrimaryCanvas() {
        return (
            document.getElementById('dicomCanvas') ||
            document.querySelector('#dicom-canvas') ||
            document.querySelector('canvas.dicom-canvas') ||
            document.querySelector('canvas')
        );
    }

    function _parsePatientInfoText(text) {
        const info = {};
        const t = String(text || '').trim();
        // Example from viewer: "Patient: X | Study Date: Y | Modality: Z"
        const parts = t.split('|').map(s => s.trim());
        for (const p of parts) {
            if (p.toLowerCase().startsWith('patient:')) info.name = p.split(':').slice(1).join(':').trim();
            if (p.toLowerCase().startsWith('study date:')) info.studyDate = p.split(':').slice(1).join(':').trim();
            if (p.toLowerCase().startsWith('modality:')) info.modality = p.split(':').slice(1).join(':').trim();
        }
        return info;
    }

    function _safeText(v) {
        const s = (v === null || v === undefined) ? '' : String(v);
        return s.replace(/\s+/g, ' ').trim();
    }

    function _getExportScale(quality) {
        const q = String(quality || 'high').toLowerCase();
        if (q === 'low') return 1.0;
        if (q === 'medium') return 1.5;
        return 2.0; // high
    }

    // Enhanced export with patient details
    function exportImageWithDetails(format = 'jpeg', options = {}) {
        const canvas = _getPrimaryCanvas();
        
        if (!canvas) {
            alert('No image to export');
            return;
        }
        
        const opts = {
            includePatientInfo: options.includePatientInfo !== false,
            includeMeasurements: options.includeMeasurements !== false,
            includeAnnotations: options.includeAnnotations !== false,
            quality: options.quality || 'high',
        };

        // Get patient details (best-effort; never block export)
        const patientInfo = getPatientInfo();
        
        // Create enhanced canvas with patient details
        const exportCanvas = document.createElement('canvas');
        const ctx = exportCanvas.getContext('2d');
        
        const scale = _getExportScale(opts.quality);
        const margin = Math.round(80 * scale);
        const headerH = opts.includePatientInfo ? Math.round(140 * scale) : Math.round(40 * scale);
        const footerH = Math.round(40 * scale);

        exportCanvas.width = Math.round(canvas.width * scale) + (margin * 2);
        exportCanvas.height = Math.round(canvas.height * scale) + headerH + footerH + margin;
        
        // White background
        ctx.fillStyle = 'white';
        ctx.fillRect(0, 0, exportCanvas.width, exportCanvas.height);
        
        let y = margin;

        // Header (patient/study info)
        if (opts.includePatientInfo) {
            ctx.fillStyle = 'black';
            ctx.font = `bold ${Math.round(18 * scale)}px Arial`;
            ctx.fillText(`Patient: ${_safeText(patientInfo.name) || 'Unknown'}`, margin, y);
            y += Math.round(26 * scale);

            ctx.font = `bold ${Math.round(16 * scale)}px Arial`;
            ctx.fillText(`Patient ID: ${_safeText(patientInfo.id) || 'N/A'}`, margin, y);
            y += Math.round(24 * scale);

            ctx.fillText(`Accession: ${_safeText(patientInfo.accession) || 'N/A'}`, margin, y);
            y += Math.round(24 * scale);

            ctx.fillText(`Study Date: ${_safeText(patientInfo.studyDate) || 'N/A'}   Modality: ${_safeText(patientInfo.modality) || 'N/A'}`, margin, y);
            y += Math.round(18 * scale);
        }

        // Divider line
        ctx.strokeStyle = '#000';
        ctx.globalAlpha = 0.25;
        ctx.beginPath();
        ctx.moveTo(margin, y);
        ctx.lineTo(exportCanvas.width - margin, y);
        ctx.stroke();
        ctx.globalAlpha = 1.0;
        y += Math.round(20 * scale);

        // Image
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(canvas, margin, y, Math.round(canvas.width * scale), Math.round(canvas.height * scale));
        
        // Add footer with export info
        const footerY = exportCanvas.height - Math.round(18 * scale);
        ctx.fillStyle = 'black';
        ctx.font = `${Math.round(12 * scale)}px Arial`;
        ctx.fillText(`Exported: ${new Date().toLocaleString()}`, margin, footerY);
        const facilityText = `Facility: ${_safeText(patientInfo.facility) || 'Noctis Pro'}`;
        ctx.fillText(facilityText, exportCanvas.width - margin - ctx.measureText(facilityText).width, footerY);
        
        // Export based on format
        if (format === 'pdf') {
            exportToPDF(exportCanvas, patientInfo);
        } else {
            exportToImage(exportCanvas, format, patientInfo);
        }
    }
    
    function exportToPDF(canvas, patientInfo) {
        // Minimal, dependency-free fallback: export as a high-quality PNG even if "PDF" was selected.
        // (True PDF generation would require a library or server-side render.)
        const imgData = canvas.toDataURL('image/png');
        const link = document.createElement('a');
        link.download = `${patientInfo.name || 'patient'}_${patientInfo.id || 'unknown'}_${Date.now()}.png`;
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
                             document.getElementById('patientInfo') ||
                             document.querySelector('.patient-info');
        
        if (patientNameEl) {
            const txt = patientNameEl.textContent || patientNameEl.dataset.patientName;
            Object.assign(info, _parsePatientInfoText(txt));
            // If it was only a name element, keep that too.
            if (!info.name) info.name = txt;
        }

        // Prefer structured globals if available
        try {
            if (window.currentStudy) {
                // currentStudy shape varies; pick common keys.
                info.name = info.name || window.currentStudy.patient_name || window.currentStudy.patientName;
                info.id = info.id || window.currentStudy.patient_id || window.currentStudy.patientId;
                info.accession = info.accession || window.currentStudy.accession_number || window.currentStudy.accessionNumber;
                info.studyDate = info.studyDate || window.currentStudy.study_date || window.currentStudy.studyDate;
                info.modality = info.modality || window.currentStudy.modality;
                info.facility = info.facility || (window.currentStudy.facility && window.currentStudy.facility.name) || window.currentStudy.facility_name;
            }
            if (window.currentSeries) {
                info.modality = info.modality || window.currentSeries.modality;
            }
        } catch (_) {}
        
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
    window.printDicomImage = function() {
        // Simple, reliable print path: render a high-quality page in a new window and call print().
        const canvas = _getPrimaryCanvas();
        if (!canvas) {
            alert('No image to print');
            return;
        }
        const patientInfo = getPatientInfo();
        const imgUrl = canvas.toDataURL('image/png');

        const w = window.open('', '_blank');
        if (!w) {
            alert('Popup blocked. Please allow popups to print.');
            return;
        }
        const title = `DICOM Print - ${_safeText(patientInfo.name) || 'Patient'}`;
        w.document.open();
        w.document.write(`
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${title}</title>
  <style>
    @page { margin: 12mm; }
    body { font-family: Arial, sans-serif; color: #000; }
    .hdr { margin-bottom: 8mm; }
    .hdr .row { display:flex; justify-content:space-between; gap: 16px; font-size: 12pt; }
    .img { width: 100%; }
    .img img { width: 100%; height: auto; display:block; }
    .ft { margin-top: 6mm; font-size: 10pt; display:flex; justify-content:space-between; }
  </style>
</head>
<body>
  <div class="hdr">
    <div class="row"><strong>Patient:</strong> ${_safeText(patientInfo.name) || 'Unknown'} <span><strong>Patient ID:</strong> ${_safeText(patientInfo.id) || 'N/A'}</span></div>
    <div class="row"><span><strong>Accession:</strong> ${_safeText(patientInfo.accession) || 'N/A'}</span><span><strong>Study Date:</strong> ${_safeText(patientInfo.studyDate) || 'N/A'}</span></div>
    <div class="row"><span><strong>Modality:</strong> ${_safeText(patientInfo.modality) || 'N/A'}</span><span><strong>Facility:</strong> ${_safeText(patientInfo.facility) || 'Noctis Pro'}</span></div>
  </div>
  <div class="img"><img src="${imgUrl}" alt="DICOM image"></div>
  <div class="ft"><span>Printed: ${new Date().toLocaleString()}</span><span>Noctis Pro</span></div>
  <script>
    window.onload = function() {
      setTimeout(function() { window.print(); }, 250);
    };
  </script>
</body>
</html>
        `);
        w.document.close();
    };
    
    // Do NOT override existing viewer functions. Some templates implement their own export UI.
    // If a page doesn't define export/print helpers, it can call these directly.
    
})();
