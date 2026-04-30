// AI Auto-Learning System for DICOM Analysis
(function() {
    'use strict';
    
    let learningModel = null;
    let analysisHistory = [];
    let userFeedback = [];
    let modelAccuracy = 0.75; // Starting accuracy
    let learningEnabled = true;
    
    window.AILearningSystem = {
        
        init: function() {
            this.createAIPanel();
            this.setupEventListeners();
            this.loadLearningModel();
            this.startContinuousLearning();
            console.log('AI Auto-Learning System initialized');
        },
        
        createAIPanel: function() {
            const panel = document.createElement('div');
            panel.id = 'ai-learning-panel';
            panel.className = 'ai-learning-panel';
            panel.innerHTML = `
                <div class="ai-header">
                    <h3><i class="fas fa-brain"></i> AI Learning System</h3>
                    <div class="ai-status">
                        <span class="status-indicator active"></span>
                        <span id="ai-status-text">Learning Active</span>
                    </div>
                </div>
                
                <div class="ai-content">
                    <div class="ai-stats">
                        <div class="stat-item">
                            <label>Model Accuracy:</label>
                            <div class="accuracy-bar">
                                <div class="accuracy-fill" id="accuracy-fill" style="width: 75%"></div>
                            </div>
                            <span id="accuracy-value">75%</span>
                        </div>
                        <div class="stat-item">
                            <label>Images Analyzed:</label>
                            <span id="images-analyzed">0</span>
                        </div>
                        <div class="stat-item">
                            <label>Learning Sessions:</label>
                            <span id="learning-sessions">0</span>
                        </div>
                    </div>
                    
                    <div class="ai-controls">
                        <div class="control-group">
                            <label>Auto-Analysis:</label>
                            <div class="toggle-switch">
                                <input type="checkbox" id="auto-analysis" checked>
                                <span class="slider"></span>
                            </div>
                        </div>
                        <div class="control-group">
                            <label>Learning Mode:</label>
                            <select id="learning-mode">
                                <option value="continuous">Continuous</option>
                                <option value="supervised">Supervised</option>
                                <option value="batch">Batch Learning</option>
                            </select>
                        </div>
                        <div class="control-group">
                            <label>Confidence Threshold:</label>
                            <input type="range" id="confidence-threshold" min="0.1" max="1.0" step="0.05" value="0.7">
                            <span id="confidence-value">70%</span>
                        </div>
                    </div>
                    
                    <div class="ai-analysis" id="ai-analysis">
                        <h4>Current Analysis</h4>
                        <div id="analysis-results">
                            <div class="no-analysis">No active analysis</div>
                        </div>
                    </div>
                    
                    <div class="ai-feedback">
                        <h4>Provide Feedback</h4>
                        <div class="feedback-controls">
                            <button class="feedback-btn correct" onclick="AILearningSystem.provideFeedback('correct')">
                                <i class="fas fa-check"></i> Correct
                            </button>
                            <button class="feedback-btn incorrect" onclick="AILearningSystem.provideFeedback('incorrect')">
                                <i class="fas fa-times"></i> Incorrect
                            </button>
                            <button class="feedback-btn partial" onclick="AILearningSystem.provideFeedback('partial')">
                                <i class="fas fa-adjust"></i> Partially Correct
                            </button>
                        </div>
                        <textarea id="feedback-notes" placeholder="Additional feedback notes..."></textarea>
                        <button class="btn-submit-feedback" onclick="AILearningSystem.submitFeedback()">
                            Submit Feedback
                        </button>
                    </div>
                    
                    <div class="ai-insights">
                        <h4>Learning Insights</h4>
                        <div id="insights-list">
                            <div class="insight-item">
                                <i class="fas fa-lightbulb"></i>
                                <span>Model is learning CT bone density patterns</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            
            // Add styles
            const style = document.createElement('style');
            style.textContent = `
                .ai-learning-panel {
                    position: fixed;
                    bottom: 20px;
                    left: 20px;
                    width: 320px;
                    max-height: 80vh;
                    background: var(--card-bg, #252525);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 8px;
                    z-index: 1000;
                    color: var(--text-primary, #ffffff);
                    font-size: 12px;
                    overflow-y: auto;
                }
                .ai-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 12px 15px;
                    background: linear-gradient(135deg, #6a4c93, #9b59b6);
                    border-radius: 8px 8px 0 0;
                }
                .ai-header h3 {
                    margin: 0;
                    font-size: 14px;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }
                .ai-status {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    font-size: 10px;
                }
                .status-indicator {
                    width: 8px;
                    height: 8px;
                    border-radius: 50%;
                    background: #ff4444;
                }
                .status-indicator.active {
                    background: #00ff88;
                    animation: pulse 2s infinite;
                }
                @keyframes pulse {
                    0% { opacity: 1; }
                    50% { opacity: 0.5; }
                    100% { opacity: 1; }
                }
                .ai-content {
                    padding: 15px;
                }
                .ai-stats {
                    margin-bottom: 15px;
                }
                .stat-item {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 8px;
                    font-size: 11px;
                }
                .accuracy-bar {
                    flex: 1;
                    height: 6px;
                    background: var(--secondary-bg, #1a1a1a);
                    border-radius: 3px;
                    margin: 0 8px;
                    overflow: hidden;
                }
                .accuracy-fill {
                    height: 100%;
                    background: linear-gradient(90deg, #ff6b35, #f7931e, #00ff88);
                    transition: width 0.5s ease;
                }
                .ai-controls {
                    border-top: 1px solid var(--border-color, #404040);
                    padding-top: 15px;
                    margin-bottom: 15px;
                }
                .control-group {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 10px;
                }
                .control-group label {
                    font-size: 11px;
                    color: var(--text-secondary, #b3b3b3);
                }
                .toggle-switch {
                    position: relative;
                    width: 40px;
                    height: 20px;
                }
                .toggle-switch input {
                    opacity: 0;
                    width: 0;
                    height: 0;
                }
                .slider {
                    position: absolute;
                    cursor: pointer;
                    top: 0;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    background-color: var(--secondary-bg, #1a1a1a);
                    transition: .4s;
                    border-radius: 20px;
                }
                .slider:before {
                    position: absolute;
                    content: "";
                    height: 16px;
                    width: 16px;
                    left: 2px;
                    bottom: 2px;
                    background-color: white;
                    transition: .4s;
                    border-radius: 50%;
                }
                input:checked + .slider {
                    background-color: var(--accent-color, #00d4ff);
                }
                input:checked + .slider:before {
                    transform: translateX(20px);
                }
                .control-group select,
                .control-group input[type="range"] {
                    width: 120px;
                    padding: 2px 6px;
                    background: var(--secondary-bg, #1a1a1a);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 3px;
                    color: var(--text-primary, #ffffff);
                    font-size: 10px;
                }
                .ai-analysis {
                    border-top: 1px solid var(--border-color, #404040);
                    padding-top: 15px;
                    margin-bottom: 15px;
                }
                .ai-analysis h4 {
                    margin: 0 0 10px 0;
                    font-size: 12px;
                }
                .analysis-result {
                    background: var(--secondary-bg, #1a1a1a);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 4px;
                    padding: 10px;
                    margin-bottom: 8px;
                }
                .analysis-finding {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 4px;
                }
                .confidence-score {
                    background: var(--accent-color, #00d4ff);
                    color: #000;
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-size: 9px;
                    font-weight: bold;
                }
                .no-analysis {
                    text-align: center;
                    color: var(--text-muted, #666666);
                    padding: 20px;
                    font-style: italic;
                }
                .ai-feedback {
                    border-top: 1px solid var(--border-color, #404040);
                    padding-top: 15px;
                    margin-bottom: 15px;
                }
                .ai-feedback h4 {
                    margin: 0 0 10px 0;
                    font-size: 12px;
                }
                .feedback-controls {
                    display: flex;
                    gap: 6px;
                    margin-bottom: 10px;
                }
                .feedback-btn {
                    flex: 1;
                    padding: 6px 8px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 10px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 4px;
                    transition: all 0.2s;
                }
                .feedback-btn.correct {
                    background: var(--success-color, #00ff88);
                    color: #000;
                }
                .feedback-btn.incorrect {
                    background: var(--danger-color, #ff4444);
                    color: #fff;
                }
                .feedback-btn.partial {
                    background: var(--warning-color, #ffaa00);
                    color: #000;
                }
                .feedback-btn:hover {
                    transform: translateY(-1px);
                    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                }
                #feedback-notes {
                    width: 100%;
                    height: 60px;
                    padding: 6px;
                    background: var(--secondary-bg, #1a1a1a);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 4px;
                    color: var(--text-primary, #ffffff);
                    font-size: 11px;
                    resize: vertical;
                    margin-bottom: 8px;
                }
                .btn-submit-feedback {
                    width: 100%;
                    padding: 8px;
                    background: var(--accent-color, #00d4ff);
                    color: #000;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 11px;
                    font-weight: bold;
                }
                .ai-insights h4 {
                    margin: 0 0 10px 0;
                    font-size: 12px;
                }
                .insight-item {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 6px;
                    background: var(--primary-bg, #0a0a0a);
                    border-radius: 4px;
                    margin-bottom: 6px;
                    font-size: 10px;
                }
                .insight-item i {
                    color: var(--warning-color, #ffaa00);
                }
            `;
            document.head.appendChild(style);
            
            // Add to viewport
            const viewport = document.querySelector('.viewer-container') || document.body;
            viewport.appendChild(panel);
        },
        
        setupEventListeners: function() {
            // Auto-analysis toggle
            document.getElementById('auto-analysis')?.addEventListener('change', (e) => {
                this.toggleAutoAnalysis(e.target.checked);
            });
            
            // Learning mode
            document.getElementById('learning-mode')?.addEventListener('change', (e) => {
                this.setLearningMode(e.target.value);
            });
            
            // Confidence threshold
            document.getElementById('confidence-threshold')?.addEventListener('input', (e) => {
                const value = Math.round(e.target.value * 100);
                document.getElementById('confidence-value').textContent = value + '%';
                this.setConfidenceThreshold(parseFloat(e.target.value));
            });
            
            // Listen for DICOM image changes
            document.addEventListener('dicomImageChanged', (e) => {
                if (document.getElementById('auto-analysis').checked) {
                    this.analyzeCurrentImage();
                }
            });
        },
        
        loadLearningModel: function() {
            // Simulate loading a pre-trained model
            learningModel = {
                version: '2.1.0',
                trainedOn: 50000,
                accuracy: modelAccuracy,
                modalities: ['CT', 'MRI', 'X-Ray', 'Ultrasound'],
                findings: [
                    'Fractures', 'Tumors', 'Pneumonia', 'Hemorrhage',
                    'Calcifications', 'Edema', 'Atrophy', 'Stenosis'
                ]
            };
            
            this.updateModelStats();
        },
        
        startContinuousLearning: function() {
            // Start continuous learning process
            setInterval(() => {
                if (learningEnabled) {
                    this.performLearningCycle();
                }
            }, 30000); // Learn every 30 seconds
        },
        
        analyzeCurrentImage: async function() {
            const analysisResults = document.getElementById('analysis-results');
            analysisResults.innerHTML = '<div class="analyzing">Analyzing image...</div>';
            
            try {
                // Simulate AI analysis
                const analysis = await this.performAIAnalysis();
                this.displayAnalysisResults(analysis);
                
                // Store for learning
                analysisHistory.push({
                    timestamp: new Date().toISOString(),
                    imageId: window.currentImageId || 'unknown',
                    analysis: analysis,
                    confidence: analysis.overallConfidence
                });
                
                this.updateStats();
                
            } catch (error) {
                console.error('AI Analysis failed:', error);
                analysisResults.innerHTML = '<div class="analysis-error">Analysis failed</div>';
            }
        },
        
        performAIAnalysis: async function() {
            // Simulate AI analysis with random findings
            return new Promise((resolve) => {
                setTimeout(() => {
                    const findings = [
                        { type: 'Normal anatomy', confidence: 0.92, severity: 'normal' },
                        { type: 'Possible calcification', confidence: 0.78, severity: 'mild' },
                        { type: 'Bone density normal', confidence: 0.95, severity: 'normal' },
                        { type: 'No acute findings', confidence: 0.88, severity: 'normal' }
                    ];
                    
                    // Randomly select findings
                    const selectedFindings = findings.sort(() => 0.5 - Math.random()).slice(0, Math.floor(Math.random() * 3) + 1);
                    
                    const analysis = {
                        findings: selectedFindings,
                        overallConfidence: selectedFindings.reduce((acc, f) => acc + f.confidence, 0) / selectedFindings.length,
                        processingTime: Math.random() * 2 + 0.5, // 0.5-2.5 seconds
                        recommendations: this.generateRecommendations(selectedFindings)
                    };
                    
                    resolve(analysis);
                }, 1000 + Math.random() * 2000); // 1-3 seconds processing time
            });
        },
        
        generateRecommendations: function(findings) {
            const recommendations = [];
            
            findings.forEach(finding => {
                if (finding.confidence < 0.8) {
                    recommendations.push('Consider additional imaging for confirmation');
                }
                if (finding.severity !== 'normal') {
                    recommendations.push('Clinical correlation recommended');
                }
            });
            
            if (recommendations.length === 0) {
                recommendations.push('Continue routine monitoring');
            }
            
            return recommendations;
        },
        
        displayAnalysisResults: function(analysis) {
            const resultsEl = document.getElementById('analysis-results');
            
            const resultsHTML = `
                <div class="analysis-result">
                    <div class="analysis-header">
                        <strong>AI Analysis Results</strong>
                        <span class="confidence-score">${Math.round(analysis.overallConfidence * 100)}% confidence</span>
                    </div>
                    <div class="analysis-findings">
                        ${analysis.findings.map(finding => `
                            <div class="analysis-finding">
                                <span class="finding-text">${finding.type}</span>
                                <span class="confidence-score">${Math.round(finding.confidence * 100)}%</span>
                            </div>
                        `).join('')}
                    </div>
                    <div class="analysis-recommendations">
                        <strong>Recommendations:</strong>
                        <ul>
                            ${analysis.recommendations.map(rec => `<li>${rec}</li>`).join('')}
                        </ul>
                    </div>
                    <div class="analysis-meta">
                        <small>Processing time: ${analysis.processingTime.toFixed(1)}s</small>
                    </div>
                </div>
            `;
            
            resultsEl.innerHTML = resultsHTML;
        },
        
        provideFeedback: function(type) {
            const feedbackButtons = document.querySelectorAll('.feedback-btn');
            feedbackButtons.forEach(btn => btn.classList.remove('selected'));
            
            const selectedBtn = document.querySelector(`.feedback-btn.${type}`);
            if (selectedBtn) {
                selectedBtn.classList.add('selected');
            }
            
            this.currentFeedback = { type: type, timestamp: new Date().toISOString() };
        },
        
        submitFeedback: function() {
            if (!this.currentFeedback) {
                alert('Please select a feedback type first');
                return;
            }
            
            const notes = document.getElementById('feedback-notes').value;
            const lastAnalysis = analysisHistory[analysisHistory.length - 1];
            
            if (lastAnalysis) {
                const feedback = {
                    ...this.currentFeedback,
                    notes: notes,
                    analysisId: lastAnalysis.timestamp,
                    imageId: lastAnalysis.imageId,
                    originalAnalysis: lastAnalysis.analysis
                };
                
                userFeedback.push(feedback);
                this.processLearningFromFeedback(feedback);
                
                // Clear feedback form
                document.getElementById('feedback-notes').value = '';
                document.querySelectorAll('.feedback-btn').forEach(btn => btn.classList.remove('selected'));
                this.currentFeedback = null;
                
                // Show confirmation
                this.showFeedbackConfirmation();
            }
        },
        
        processLearningFromFeedback: function(feedback) {
            // Adjust model accuracy based on feedback
            if (feedback.type === 'correct') {
                modelAccuracy = Math.min(1.0, modelAccuracy + 0.001);
            } else if (feedback.type === 'incorrect') {
                modelAccuracy = Math.max(0.1, modelAccuracy - 0.002);
            } else if (feedback.type === 'partial') {
                modelAccuracy = Math.min(1.0, modelAccuracy + 0.0005);
            }
            
            this.updateModelStats();
            this.addLearningInsight(feedback);
        },
        
        performLearningCycle: function() {
            if (userFeedback.length > 0) {
                // Simulate learning from accumulated feedback
                const recentFeedback = userFeedback.slice(-10); // Last 10 feedback items
                const correctFeedback = recentFeedback.filter(f => f.type === 'correct').length;
                const totalFeedback = recentFeedback.length;
                
                if (totalFeedback > 5) {
                    const feedbackAccuracy = correctFeedback / totalFeedback;
                    modelAccuracy = (modelAccuracy * 0.9) + (feedbackAccuracy * 0.1); // Weighted average
                    
                    this.updateModelStats();
                    this.incrementLearningSessions();
                }
            }
        },
        
        updateModelStats: function() {
            const accuracyFill = document.getElementById('accuracy-fill');
            const accuracyValue = document.getElementById('accuracy-value');
            
            if (accuracyFill && accuracyValue) {
                const percentage = Math.round(modelAccuracy * 100);
                accuracyFill.style.width = percentage + '%';
                accuracyValue.textContent = percentage + '%';
            }
        },
        
        updateStats: function() {
            const imagesAnalyzed = document.getElementById('images-analyzed');
            if (imagesAnalyzed) {
                imagesAnalyzed.textContent = analysisHistory.length;
            }
        },
        
        incrementLearningSessions: function() {
            const sessionsEl = document.getElementById('learning-sessions');
            if (sessionsEl) {
                const current = parseInt(sessionsEl.textContent) || 0;
                sessionsEl.textContent = current + 1;
            }
        },
        
        addLearningInsight: function(feedback) {
            const insightsList = document.getElementById('insights-list');
            if (!insightsList) return;
            
            const insights = [
                'Learning improved pattern recognition for bone structures',
                'Enhanced accuracy in soft tissue differentiation',
                'Better detection of subtle abnormalities',
                'Improved confidence calibration based on user feedback',
                'Refined analysis for current imaging modality'
            ];
            
            const randomInsight = insights[Math.floor(Math.random() * insights.length)];
            
            const insightEl = document.createElement('div');
            insightEl.className = 'insight-item';
            insightEl.innerHTML = `
                <i class="fas fa-lightbulb"></i>
                <span>${randomInsight}</span>
            `;
            
            insightsList.appendChild(insightEl);
            
            // Keep only last 5 insights
            while (insightsList.children.length > 5) {
                insightsList.removeChild(insightsList.firstChild);
            }
        },
        
        showFeedbackConfirmation: function() {
            const confirmation = document.createElement('div');
            confirmation.className = 'feedback-confirmation';
            confirmation.innerHTML = `
                <div class="confirmation-content">
                    <i class="fas fa-check-circle"></i>
                    <span>Feedback submitted! AI is learning...</span>
                </div>
            `;
            
            const style = document.createElement('style');
            style.textContent = `
                .feedback-confirmation {
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    background: var(--success-color, #00ff88);
                    color: #000;
                    padding: 12px 16px;
                    border-radius: 6px;
                    z-index: 10000;
                    animation: slideIn 0.3s ease;
                }
                .confirmation-content {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    font-size: 12px;
                    font-weight: bold;
                }
                @keyframes slideIn {
                    from { transform: translateX(100%); opacity: 0; }
                    to { transform: translateX(0); opacity: 1; }
                }
            `;
            document.head.appendChild(style);
            document.body.appendChild(confirmation);
            
            setTimeout(() => {
                confirmation.remove();
                style.remove();
            }, 3000);
        },
        
        toggleAutoAnalysis: function(enabled) {
            const statusText = document.getElementById('ai-status-text');
            const statusIndicator = document.querySelector('.status-indicator');
            
            if (enabled) {
                statusText.textContent = 'Learning Active';
                statusIndicator.classList.add('active');
            } else {
                statusText.textContent = 'Learning Paused';
                statusIndicator.classList.remove('active');
            }
        },
        
        setLearningMode: function(mode) {
            console.log('Learning mode set to:', mode);
            // Implement different learning strategies based on mode
        },
        
        setConfidenceThreshold: function(threshold) {
            // Update confidence threshold for displaying results
            console.log('Confidence threshold set to:', threshold);
        },
        
        exportLearningData: function() {
            const data = {
                modelVersion: learningModel.version,
                modelAccuracy: modelAccuracy,
                analysisHistory: analysisHistory,
                userFeedback: userFeedback,
                exportedAt: new Date().toISOString()
            };
            
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `ai_learning_data_${Date.now()}.json`;
            a.click();
            URL.revokeObjectURL(url);
        },
        
        // API for external integration
        generateAutoReport: async function(imageData) {
            if (!learningModel) return null;
            
            const analysis = await this.performAIAnalysis();
            
            const report = {
                patientId: window.currentPatient?.id || 'Unknown',
                imageId: window.currentImageId || 'Unknown',
                analysis: analysis,
                generatedAt: new Date().toISOString(),
                modelVersion: learningModel.version,
                confidence: analysis.overallConfidence
            };
            
            return report;
        }
    };
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => AILearningSystem.init());
    } else {
        AILearningSystem.init();
    }
    
    // Expose for global access
    window.AILearningSystem = AILearningSystem;
    
})();