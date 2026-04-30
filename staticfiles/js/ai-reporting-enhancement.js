
// AI Reporting Enhancement
(function() {
    'use strict';
    
    // AI Auto-reporting functionality
    window.AIReporting = {
        
        // Auto-generate report based on DICOM analysis
        generateAutoReport: async function(studyId, imageData) {
            try {
                const analysis = await this.analyzeImage(imageData);
                const report = await this.createReport(studyId, analysis);
                return report;
            } catch (error) {
                console.error('AI reporting error:', error);
                throw error;
            }
        },
        
        // Analyze image for key findings
        analyzeImage: async function(imageData) {
            // Placeholder for AI analysis
            // In a real implementation, this would call an AI service
            return {
                findings: [
                    'Image quality: Good',
                    'Contrast enhancement: Present',
                    'Anatomical structures: Normal'
                ],
                measurements: {
                    area: '25.4 cm²',
                    volume: '180 ml'
                },
                recommendations: 'Follow-up in 6 months'
            };
        },
        
        // Create structured report
        createReport: async function(studyId, analysis) {
            const reportData = {
                study_id: studyId,
                generated_by: 'AI_SYSTEM',
                findings: analysis.findings.join('\n'),
                measurements: JSON.stringify(analysis.measurements),
                recommendations: analysis.recommendations,
                confidence_score: 0.85
            };
            
            const response = await fetch('/reports/api/ai-report/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify(reportData)
            });
            
            if (!response.ok) {
                throw new Error('Failed to create AI report');
            }
            
            return await response.json();
        },
        
        // Enhanced reporting UI
        showReportingPanel: function() {
            const panel = this.createReportingPanel();
            document.body.appendChild(panel);
        },
        
        createReportingPanel: function() {
            const panel = document.createElement('div');
            panel.id = 'ai-reporting-panel';
            panel.innerHTML = `
                <div class="reporting-overlay">
                    <div class="reporting-dialog">
                        <h3>AI-Assisted Reporting</h3>
                        <div class="reporting-content">
                            <div class="analysis-section">
                                <h4>Automated Analysis</h4>
                                <div id="ai-findings"></div>
                            </div>
                            <div class="measurements-section">
                                <h4>Measurements</h4>
                                <div id="ai-measurements"></div>
                            </div>
                            <div class="recommendations-section">
                                <h4>Recommendations</h4>
                                <div id="ai-recommendations"></div>
                            </div>
                        </div>
                        <div class="reporting-actions">
                            <button onclick="AIReporting.generateReport()" class="btn-primary">
                                Generate Report
                            </button>
                            <button onclick="AIReporting.closePanel()" class="btn-secondary">
                                Close
                            </button>
                        </div>
                    </div>
                </div>
            `;
            
            // Add styles
            const style = document.createElement('style');
            style.textContent = `
                .reporting-overlay {
                    position: fixed;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    background: rgba(0, 0, 0, 0.8);
                    z-index: 10000;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }
                .reporting-dialog {
                    background: var(--card-bg, #252525);
                    border-radius: 8px;
                    padding: 20px;
                    max-width: 600px;
                    width: 90%;
                    color: var(--text-primary, #ffffff);
                }
                .analysis-section, .measurements-section, .recommendations-section {
                    margin: 15px 0;
                    padding: 10px;
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 4px;
                }
                .reporting-actions {
                    display: flex;
                    gap: 10px;
                    justify-content: flex-end;
                    margin-top: 20px;
                }
            `;
            document.head.appendChild(style);
            
            return panel;
        },
        
        closePanel: function() {
            const panel = document.getElementById('ai-reporting-panel');
            if (panel) {
                panel.remove();
            }
        }
    };
    
    function getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
               document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
               getCookie('csrftoken');
    }
    
    function getCookie(name) {
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
    
})();
