/**
 * Button Functionality Test Suite for NoctisPro PACS
 * Tests all button functionality to ensure everything works properly
 */

class ButtonFunctionalityTest {
    constructor() {
        this.testResults = [];
        this.init();
    }

    init() {
        console.log('🧪 Starting Button Functionality Tests...');
        this.runAllTests();
    }

    async runAllTests() {
        // Test basic button enhancement
        await this.testButtonEnhancement();
        
        // Test navigation functions
        await this.testNavigationFunctions();
        
        // Test API functions
        await this.testAPIFunctions();
        
        // Test DICOM viewer functions
        await this.testDicomViewerFunctions();
        
        // Test utility functions
        await this.testUtilityFunctions();
        
        // Display results
        this.displayTestResults();
    }

    async testButtonEnhancement() {
        console.log('🔧 Testing button enhancement...');
        
        try {
            // Test if buttons are enhanced
            const buttons = document.querySelectorAll('button, .btn, .tool');
            const enhancedButtons = document.querySelectorAll('.noctispro-button-enhanced');
            
            this.addTestResult('Button Enhancement', 
                enhancedButtons.length > 0 ? 'PASS' : 'FAIL',
                `Enhanced ${enhancedButtons.length} of ${buttons.length} buttons`
            );
            
            // Test ripple effect creation
            if (window.noctisProButtonManager) {
                const testButton = document.createElement('button');
                testButton.textContent = 'Test';
                document.body.appendChild(testButton);
                
                window.noctisProButtonManager.enhanceButton(testButton);
                
                this.addTestResult('Ripple Enhancement', 
                    testButton.classList.contains('noctispro-button-enhanced') ? 'PASS' : 'FAIL',
                    'Button ripple enhancement working'
                );
                
                document.body.removeChild(testButton);
            }
        } catch (error) {
            this.addTestResult('Button Enhancement', 'ERROR', error.message);
        }
    }

    async testNavigationFunctions() {
        console.log('🧭 Testing navigation functions...');
        
        const navigationTests = [
            { name: 'launchDicomViewer', func: window.launchDicomViewer },
            { name: 'loadFromDirectory', func: window.loadFromDirectory },
            { name: 'uploadStudies', func: window.uploadStudies },
            { name: 'openReport', func: window.openReport },
            { name: 'printStudy', func: window.printStudy }
        ];

        navigationTests.forEach(test => {
            try {
                const exists = typeof test.func === 'function';
                this.addTestResult(`Navigation: ${test.name}`, 
                    exists ? 'PASS' : 'FAIL',
                    exists ? 'Function available' : 'Function missing'
                );
            } catch (error) {
                this.addTestResult(`Navigation: ${test.name}`, 'ERROR', error.message);
            }
        });
    }

    async testAPIFunctions() {
        console.log('🌐 Testing API functions...');
        
        try {
            // Test CSRF token retrieval
            const csrfToken = window.noctisProButtonManager?.getCSRFToken();
            this.addTestResult('CSRF Token', 
                csrfToken ? 'PASS' : 'FAIL',
                csrfToken ? 'Token retrieved' : 'No token found'
            );

            // Test API request function
            if (window.noctisProButtonManager?.apiRequest) {
                try {
                    // Test with a simple endpoint that should exist
                    const response = await window.noctisProButtonManager.apiRequest('/worklist/api/upload-stats/');
                    this.addTestResult('API Request', 'PASS', 'API request function working');
                } catch (error) {
                    this.addTestResult('API Request', 'PARTIAL', `Function exists but endpoint failed: ${error.message}`);
                }
            } else {
                this.addTestResult('API Request', 'FAIL', 'API request function not available');
            }
        } catch (error) {
            this.addTestResult('API Functions', 'ERROR', error.message);
        }
    }

    async testDicomViewerFunctions() {
        console.log('🖼️ Testing DICOM viewer functions...');
        
        const dicomFunctions = [
            { name: 'setTool', func: window.setTool },
            { name: 'resetView', func: window.resetView },
            { name: 'toggleCrosshair', func: window.toggleCrosshair },
            { name: 'toggleInvert', func: window.toggleInvert },
            { name: 'applyPreset', func: window.applyPreset },
            { name: 'loadFromLocalFiles', func: window.loadFromLocalFiles },
            { name: 'exportImage', func: window.exportImage }
        ];

        dicomFunctions.forEach(test => {
            try {
                const exists = typeof test.func === 'function';
                this.addTestResult(`DICOM: ${test.name}`, 
                    exists ? 'PASS' : 'FAIL',
                    exists ? 'Function available' : 'Function missing'
                );
            } catch (error) {
                this.addTestResult(`DICOM: ${test.name}`, 'ERROR', error.message);
            }
        });

        // Test DICOM viewer enhanced class
        if (window.dicomViewerEnhanced) {
            this.addTestResult('DICOM Enhanced Class', 'PASS', 'Enhanced DICOM viewer loaded');
        } else {
            this.addTestResult('DICOM Enhanced Class', 'FAIL', 'Enhanced DICOM viewer not loaded');
        }
    }

    async testUtilityFunctions() {
        console.log('🔧 Testing utility functions...');
        
        try {
            // Test toast notification
            if (window.noctisProButtonManager?.showToast) {
                window.noctisProButtonManager.showToast('Test notification', 'info', 1000);
                this.addTestResult('Toast Notifications', 'PASS', 'Toast system working');
            } else {
                this.addTestResult('Toast Notifications', 'FAIL', 'Toast system not available');
            }

            // Test button loading state
            const testButton = document.createElement('button');
            testButton.textContent = 'Test Button';
            document.body.appendChild(testButton);

            if (window.noctisProButtonManager?.setButtonLoading) {
                window.noctisProButtonManager.setButtonLoading(testButton, true);
                const isLoading = testButton.classList.contains('noctispro-loading');
                window.noctisProButtonManager.setButtonLoading(testButton, false);
                
                this.addTestResult('Button Loading State', 
                    isLoading ? 'PASS' : 'FAIL',
                    'Loading state management working'
                );
            } else {
                this.addTestResult('Button Loading State', 'FAIL', 'Loading state function not available');
            }

            document.body.removeChild(testButton);

            // Test filter reset
            if (window.resetFilters) {
                this.addTestResult('Reset Filters', 'PASS', 'Reset filters function available');
            } else {
                this.addTestResult('Reset Filters', 'FAIL', 'Reset filters function missing');
            }

        } catch (error) {
            this.addTestResult('Utility Functions', 'ERROR', error.message);
        }
    }

    addTestResult(testName, status, details) {
        this.testResults.push({
            name: testName,
            status: status,
            details: details,
            timestamp: new Date().toISOString()
        });

        // Log result
        const statusIcon = status === 'PASS' ? '✅' : status === 'FAIL' ? '❌' : status === 'PARTIAL' ? '⚠️' : '🚨';
        console.log(`${statusIcon} ${testName}: ${status} - ${details}`);
    }

    displayTestResults() {
        console.log('\n📊 Button Functionality Test Results:');
        console.log('=====================================');
        
        const passed = this.testResults.filter(r => r.status === 'PASS').length;
        const failed = this.testResults.filter(r => r.status === 'FAIL').length;
        const partial = this.testResults.filter(r => r.status === 'PARTIAL').length;
        const errors = this.testResults.filter(r => r.status === 'ERROR').length;
        const total = this.testResults.length;

        console.log(`✅ Passed: ${passed}`);
        console.log(`❌ Failed: ${failed}`);
        console.log(`⚠️ Partial: ${partial}`);
        console.log(`🚨 Errors: ${errors}`);
        console.log(`📊 Total: ${total}`);
        console.log(`📈 Success Rate: ${Math.round((passed / total) * 100)}%`);

        // Create visual test results
        this.createTestResultsDisplay();

        // Show summary toast
        if (window.noctisProButtonManager?.showToast) {
            const successRate = Math.round((passed / total) * 100);
            const message = `Button Tests Complete: ${successRate}% success rate (${passed}/${total})`;
            const type = successRate >= 80 ? 'success' : successRate >= 60 ? 'warning' : 'error';
            window.noctisProButtonManager.showToast(message, type, 5000);
        }
    }

    createTestResultsDisplay() {
        // Remove any existing test results
        const existingResults = document.getElementById('button-test-results');
        if (existingResults) {
            existingResults.remove();
        }

        // Create test results panel
        const resultsPanel = document.createElement('div');
        resultsPanel.id = 'button-test-results';
        resultsPanel.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: var(--card-bg, #252525);
            border: 1px solid var(--border-color, #404040);
            border-radius: 8px;
            padding: 16px;
            max-width: 400px;
            max-height: 300px;
            overflow-y: auto;
            z-index: 10000;
            font-family: 'Segoe UI', monospace;
            font-size: 11px;
            color: var(--text-primary, #ffffff);
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.3);
        `;

        const header = document.createElement('div');
        header.style.cssText = `
            font-weight: bold;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border-color, #404040);
            color: var(--accent-color, #00d4ff);
        `;
        header.textContent = '🧪 Button Test Results';

        const closeButton = document.createElement('button');
        closeButton.innerHTML = '×';
        closeButton.style.cssText = `
            position: absolute;
            top: 8px;
            right: 8px;
            background: none;
            border: none;
            color: var(--text-muted, #666666);
            cursor: pointer;
            font-size: 16px;
            width: 24px;
            height: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
        `;
        closeButton.onclick = () => resultsPanel.remove();

        resultsPanel.appendChild(header);
        resultsPanel.appendChild(closeButton);

        // Add summary
        const passed = this.testResults.filter(r => r.status === 'PASS').length;
        const total = this.testResults.length;
        const successRate = Math.round((passed / total) * 100);

        const summary = document.createElement('div');
        summary.style.cssText = `margin-bottom: 12px; font-weight: bold;`;
        summary.innerHTML = `Success Rate: <span style="color: ${successRate >= 80 ? 'var(--success-color, #00ff88)' : successRate >= 60 ? 'var(--warning-color, #ffaa00)' : 'var(--danger-color, #ff4444)'}">${successRate}%</span> (${passed}/${total})`;
        resultsPanel.appendChild(summary);

        // Add individual results
        this.testResults.forEach(result => {
            const resultDiv = document.createElement('div');
            resultDiv.style.cssText = `
                margin-bottom: 6px;
                padding: 4px;
                border-radius: 3px;
                background: rgba(255, 255, 255, 0.05);
            `;

            const statusColor = result.status === 'PASS' ? 'var(--success-color, #00ff88)' : 
                               result.status === 'FAIL' ? 'var(--danger-color, #ff4444)' : 
                               result.status === 'PARTIAL' ? 'var(--warning-color, #ffaa00)' : 
                               'var(--danger-color, #ff4444)';

            const statusIcon = result.status === 'PASS' ? '✅' : 
                              result.status === 'FAIL' ? '❌' : 
                              result.status === 'PARTIAL' ? '⚠️' : '🚨';

            resultDiv.innerHTML = `
                <div style="font-weight: bold;">${statusIcon} ${result.name}</div>
                <div style="color: ${statusColor}; font-size: 10px;">${result.status}</div>
                <div style="color: var(--text-secondary, #b3b3b3); font-size: 10px;">${result.details}</div>
            `;

            resultsPanel.appendChild(resultDiv);
        });

        document.body.appendChild(resultsPanel);

        // Auto-hide after 30 seconds
        setTimeout(() => {
            if (resultsPanel.parentNode) {
                resultsPanel.remove();
            }
        }, 30000);
    }
}

// Auto-run tests when page loads (after a delay to ensure everything is loaded)
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(() => {
        // Only run tests if we're in development or if explicitly requested
        const runTests = window.location.search.includes('test=buttons') || 
                         window.location.hostname === 'localhost' ||
                         window.localStorage.getItem('noctispro-run-button-tests') === 'true';
        
        if (runTests) {
            new ButtonFunctionalityTest();
        }
    }, 2000);
});

// Allow manual test execution
window.runButtonTests = function() {
    new ButtonFunctionalityTest();
};

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ButtonFunctionalityTest;
}