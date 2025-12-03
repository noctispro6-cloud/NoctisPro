// Advanced Backup System for Admin Panel
(function() {
    'use strict';
    
    let backupConfig = {
        enabled: false,
        frequency: 'daily',
        time: '02:00',
        remoteServers: [],
        localPath: '/backup',
        retention: 30, // days
        compression: true,
        encryption: false
    };
    
    let backupHistory = [];
    let isBackupRunning = false;
    
    window.BackupSystem = {
        
        init: function() {
            this.createBackupPanel();
            this.setupEventListeners();
            this.loadBackupConfig();
            this.startScheduler();
            console.log('Backup System initialized');
        },
        
        showPanel: function() {
            const panel = document.getElementById('backup-panel');
            if (panel) {
                panel.classList.add('show');
                panel.style.display = 'block';
                console.log('Backup panel shown');
            }
        },
        
        hidePanel: function() {
            const panel = document.getElementById('backup-panel');
            if (panel) {
                panel.classList.remove('show');
                panel.style.display = 'none';
                console.log('Backup panel hidden');
            }
        },
        
        togglePanel: function() {
            const panel = document.getElementById('backup-panel');
            if (panel) {
                if (panel.style.display === 'none' || !panel.classList.contains('show')) {
                    this.showPanel();
                } else {
                    this.hidePanel();
                }
            }
        },
        
        createBackupPanel: function() {
            const panel = document.createElement('div');
            panel.id = 'backup-panel';
            panel.className = 'backup-panel';
            panel.innerHTML = `
                <div class="backup-header">
                    <div class="backup-title">
                        <h3><i class="fas fa-database"></i> Backup System</h3>
                        <div class="backup-status">
                            <span class="status-indicator" id="backup-status-indicator"></span>
                            <span id="backup-status-text">Idle</span>
                        </div>
                    </div>
                    <button class="backup-close-btn" onclick="BackupSystem.hidePanel()" title="Hide Backup Panel">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                
                <div class="backup-content">
                    <div class="backup-config">
                        <h4>Backup Configuration</h4>
                        
                        <div class="config-group">
                            <label>
                                <input type="checkbox" id="backup-enabled"> Enable Automatic Backup
                            </label>
                        </div>
                        
                        <div class="config-group">
                            <label>Backup Frequency:</label>
                            <select id="backup-frequency">
                                <option value="hourly">Hourly</option>
                                <option value="daily" selected>Daily</option>
                                <option value="weekly">Weekly</option>
                                <option value="monthly">Monthly</option>
                            </select>
                        </div>
                        
                        <div class="config-group">
                            <label>Backup Time:</label>
                            <input type="time" id="backup-time" value="02:00">
                        </div>
                        
                        <div class="config-group">
                            <label>Retention Period (days):</label>
                            <input type="number" id="backup-retention" min="1" max="365" value="30">
                        </div>
                        
                        <div class="config-group">
                            <label>
                                <input type="checkbox" id="backup-compression" checked> Enable Compression
                            </label>
                        </div>
                        
                        <div class="config-group">
                            <label>
                                <input type="checkbox" id="backup-encryption"> Enable Encryption
                            </label>
                        </div>
                    </div>
                    
                    <div class="remote-servers">
                        <h4>Remote Backup Servers</h4>
                        <div id="servers-list">
                            <!-- Dynamic server list -->
                        </div>
                        <button class="btn-add-server" onclick="BackupSystem.showAddServerDialog()">
                            <i class="fas fa-plus"></i> Add Remote Server
                        </button>
                    </div>
                    
                    <div class="backup-actions">
                        <button id="start-backup" class="btn-primary" onclick="BackupSystem.startManualBackup()">
                            <i class="fas fa-play"></i> Start Backup Now
                        </button>
                        <button id="test-connection" class="btn-secondary" onclick="BackupSystem.testConnections()">
                            <i class="fas fa-network-wired"></i> Test Connections
                        </button>
                        <button id="restore-backup" class="btn-secondary" onclick="BackupSystem.showRestoreDialog()">
                            <i class="fas fa-undo"></i> Restore
                        </button>
                    </div>
                    
                    <div class="backup-progress" id="backup-progress" style="display: none;">
                        <div class="progress-header">
                            <span id="progress-text">Preparing backup...</span>
                            <span id="progress-percentage">0%</span>
                        </div>
                        <div class="progress-bar">
                            <div class="progress-fill" id="progress-fill"></div>
                        </div>
                        <div class="progress-details">
                            <div id="current-operation">Initializing...</div>
                            <div id="backup-size">Size: 0 MB</div>
                        </div>
                    </div>
                    
                    <div class="backup-history">
                        <h4>Backup History</h4>
                        <div class="history-controls">
                            <button class="btn-small" onclick="BackupSystem.refreshHistory()">
                                <i class="fas fa-refresh"></i> Refresh
                            </button>
                            <button class="btn-small" onclick="BackupSystem.exportHistory()">
                                <i class="fas fa-download"></i> Export Log
                            </button>
                        </div>
                        <div id="backup-history-list" class="history-list">
                            <!-- Dynamic history list -->
                        </div>
                    </div>
                </div>
            `;
            
            // Add styles
            const style = document.createElement('style');
            style.textContent = `
                .backup-panel {
                    position: fixed;
                    top: 80px;
                    right: 20px;
                    width: 400px;
                    max-height: 85vh;
                    background: var(--card-bg, #252525);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 8px;
                    z-index: 1000;
                    color: var(--text-primary, #ffffff);
                    font-size: 12px;
                    overflow-y: auto;
                    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
                    display: none;
                    animation: slideInRight 0.3s ease-out;
                }
                
                .backup-panel.show {
                    display: block;
                }
                
                @keyframes slideInRight {
                    from {
                        transform: translateX(100%);
                        opacity: 0;
                    }
                    to {
                        transform: translateX(0);
                        opacity: 1;
                    }
                }
                
                .backup-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 12px 15px;
                    background: linear-gradient(135deg, #2c3e50, #34495e);
                    border-radius: 8px 8px 0 0;
                }
                
                .backup-title {
                    display: flex;
                    flex-direction: column;
                    gap: 4px;
                }
                
                .backup-close-btn {
                    background: #e74c3c;
                    border: none;
                    color: white;
                    padding: 6px 8px;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 12px;
                    transition: all 0.2s ease;
                    display: flex;
                    align-items: center;
                    gap: 4px;
                }
                
                .backup-close-btn:hover {
                    background: #c0392b;
                    transform: scale(1.05);
                }
                .backup-header h3 {
                    margin: 0;
                    font-size: 14px;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }
                .backup-status {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    font-size: 10px;
                }
                .status-indicator {
                    width: 8px;
                    height: 8px;
                    border-radius: 50%;
                    background: #666;
                }
                .status-indicator.idle { background: #666; }
                .status-indicator.running { background: #00d4ff; animation: pulse 1s infinite; }
                .status-indicator.success { background: #00ff88; }
                .status-indicator.error { background: #ff4444; }
                .backup-content {
                    padding: 15px;
                }
                .backup-config h4,
                .remote-servers h4,
                .backup-history h4 {
                    margin: 0 0 12px 0;
                    font-size: 13px;
                    color: var(--accent-color, #00d4ff);
                    border-bottom: 1px solid var(--border-color, #404040);
                    padding-bottom: 6px;
                }
                .config-group {
                    margin-bottom: 12px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }
                .config-group label {
                    font-size: 11px;
                    color: var(--text-secondary, #b3b3b3);
                    display: flex;
                    align-items: center;
                    gap: 6px;
                }
                .config-group select,
                .config-group input[type="time"],
                .config-group input[type="number"] {
                    width: 120px;
                    padding: 4px 8px;
                    background: var(--secondary-bg, #1a1a1a);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 3px;
                    color: var(--text-primary, #ffffff);
                    font-size: 11px;
                }
                .config-group input[type="checkbox"] {
                    accent-color: var(--accent-color, #00d4ff);
                }
                .remote-servers {
                    margin: 20px 0;
                    border-top: 1px solid var(--border-color, #404040);
                    padding-top: 15px;
                }
                .server-item {
                    background: var(--secondary-bg, #1a1a1a);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 4px;
                    padding: 10px;
                    margin-bottom: 8px;
                    position: relative;
                }
                .server-info {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 4px;
                }
                .server-name {
                    font-weight: bold;
                    font-size: 11px;
                }
                .server-status {
                    font-size: 9px;
                    padding: 2px 6px;
                    border-radius: 3px;
                }
                .server-status.connected { background: var(--success-color, #00ff88); color: #000; }
                .server-status.disconnected { background: var(--danger-color, #ff4444); color: #fff; }
                .server-status.testing { background: var(--warning-color, #ffaa00); color: #000; }
                .server-details {
                    font-size: 10px;
                    color: var(--text-muted, #666);
                }
                .server-actions {
                    position: absolute;
                    top: 8px;
                    right: 8px;
                    display: flex;
                    gap: 4px;
                }
                .btn-icon {
                    background: none;
                    border: none;
                    color: var(--text-secondary, #b3b3b3);
                    cursor: pointer;
                    padding: 2px;
                    font-size: 10px;
                }
                .btn-icon:hover { color: var(--accent-color, #00d4ff); }
                .btn-add-server {
                    width: 100%;
                    padding: 8px;
                    background: var(--secondary-bg, #1a1a1a);
                    border: 1px dashed var(--border-color, #404040);
                    color: var(--text-secondary, #b3b3b3);
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 11px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 6px;
                }
                .btn-add-server:hover {
                    background: var(--primary-bg, #0a0a0a);
                    color: var(--accent-color, #00d4ff);
                }
                .backup-actions {
                    display: flex;
                    gap: 8px;
                    margin: 20px 0;
                    border-top: 1px solid var(--border-color, #404040);
                    padding-top: 15px;
                }
                .btn-primary, .btn-secondary {
                    flex: 1;
                    padding: 8px 12px;
                    border: none;
                    border-radius: 4px;
                    font-size: 11px;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 4px;
                    transition: all 0.2s;
                }
                .btn-primary {
                    background: var(--accent-color, #00d4ff);
                    color: #000;
                }
                .btn-primary:hover { background: #00b8e6; }
                .btn-primary:disabled {
                    background: #666;
                    cursor: not-allowed;
                }
                .btn-secondary {
                    background: var(--secondary-bg, #1a1a1a);
                    color: var(--text-primary, #ffffff);
                    border: 1px solid var(--border-color, #404040);
                }
                .btn-secondary:hover { background: var(--primary-bg, #0a0a0a); }
                .backup-progress {
                    background: var(--secondary-bg, #1a1a1a);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 6px;
                    padding: 12px;
                    margin: 15px 0;
                }
                .progress-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 8px;
                    font-size: 11px;
                }
                .progress-bar {
                    width: 100%;
                    height: 8px;
                    background: var(--primary-bg, #0a0a0a);
                    border-radius: 4px;
                    overflow: hidden;
                    margin-bottom: 8px;
                }
                .progress-fill {
                    height: 100%;
                    background: linear-gradient(90deg, var(--accent-color, #00d4ff), #00ff88);
                    transition: width 0.3s ease;
                    width: 0%;
                }
                .progress-details {
                    display: flex;
                    justify-content: space-between;
                    font-size: 10px;
                    color: var(--text-muted, #666);
                }
                .backup-history {
                    border-top: 1px solid var(--border-color, #404040);
                    padding-top: 15px;
                    margin-top: 20px;
                }
                .history-controls {
                    display: flex;
                    gap: 6px;
                    margin-bottom: 10px;
                }
                .btn-small {
                    padding: 4px 8px;
                    background: var(--secondary-bg, #1a1a1a);
                    border: 1px solid var(--border-color, #404040);
                    color: var(--text-primary, #ffffff);
                    border-radius: 3px;
                    cursor: pointer;
                    font-size: 10px;
                    display: flex;
                    align-items: center;
                    gap: 4px;
                }
                .btn-small:hover { background: var(--primary-bg, #0a0a0a); }
                .history-list {
                    max-height: 200px;
                    overflow-y: auto;
                }
                .history-item {
                    background: var(--primary-bg, #0a0a0a);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 4px;
                    padding: 8px;
                    margin-bottom: 6px;
                    font-size: 10px;
                }
                .history-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 4px;
                }
                .backup-date {
                    font-weight: bold;
                }
                .backup-result {
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-size: 9px;
                }
                .backup-result.success { background: var(--success-color, #00ff88); color: #000; }
                .backup-result.failed { background: var(--danger-color, #ff4444); color: #fff; }
                .backup-result.partial { background: var(--warning-color, #ffaa00); color: #000; }
                .history-details {
                    color: var(--text-muted, #666);
                    font-size: 9px;
                }
                
                /* Modal styles */
                .modal-overlay {
                    position: fixed;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    background: rgba(0, 0, 0, 0.7);
                    z-index: 10000;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }
                .modal-content {
                    background: var(--card-bg, #252525);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 8px;
                    padding: 20px;
                    max-width: 500px;
                    width: 90%;
                    color: var(--text-primary, #ffffff);
                }
                .modal-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 15px;
                    padding-bottom: 10px;
                    border-bottom: 1px solid var(--border-color, #404040);
                }
                .modal-close {
                    background: none;
                    border: none;
                    color: var(--text-secondary, #b3b3b3);
                    font-size: 20px;
                    cursor: pointer;
                }
                .form-group {
                    margin-bottom: 15px;
                }
                .form-group label {
                    display: block;
                    margin-bottom: 5px;
                    font-size: 12px;
                    color: var(--text-secondary, #b3b3b3);
                }
                .form-group input,
                .form-group select {
                    width: 100%;
                    padding: 8px;
                    background: var(--secondary-bg, #1a1a1a);
                    border: 1px solid var(--border-color, #404040);
                    border-radius: 4px;
                    color: var(--text-primary, #ffffff);
                    font-size: 12px;
                }
                .modal-actions {
                    display: flex;
                    gap: 10px;
                    justify-content: flex-end;
                    margin-top: 20px;
                }
            `;
            document.head.appendChild(style);
            
            // Add to admin panel or viewport
            const adminPanel = document.querySelector('.admin-panel') || 
                             document.querySelector('.viewer-container') || 
                             document.body;
            adminPanel.appendChild(panel);
        },
        
        setupEventListeners: function() {
            // Configuration changes
            document.getElementById('backup-enabled')?.addEventListener('change', (e) => {
                this.updateConfig('enabled', e.target.checked);
            });
            
            document.getElementById('backup-frequency')?.addEventListener('change', (e) => {
                this.updateConfig('frequency', e.target.value);
            });
            
            document.getElementById('backup-time')?.addEventListener('change', (e) => {
                this.updateConfig('time', e.target.value);
            });
            
            document.getElementById('backup-retention')?.addEventListener('change', (e) => {
                this.updateConfig('retention', parseInt(e.target.value));
            });
            
            document.getElementById('backup-compression')?.addEventListener('change', (e) => {
                this.updateConfig('compression', e.target.checked);
            });
            
            document.getElementById('backup-encryption')?.addEventListener('change', (e) => {
                this.updateConfig('encryption', e.target.checked);
            });
        },
        
        loadBackupConfig: function() {
            // Load configuration from localStorage or server
            const saved = localStorage.getItem('backupConfig');
            if (saved) {
                backupConfig = { ...backupConfig, ...JSON.parse(saved) };
            }
            
            // Update UI
            document.getElementById('backup-enabled').checked = backupConfig.enabled;
            document.getElementById('backup-frequency').value = backupConfig.frequency;
            document.getElementById('backup-time').value = backupConfig.time;
            document.getElementById('backup-retention').value = backupConfig.retention;
            document.getElementById('backup-compression').checked = backupConfig.compression;
            document.getElementById('backup-encryption').checked = backupConfig.encryption;
            
            this.updateServersList();
            this.loadBackupHistory();
        },
        
        updateConfig: function(key, value) {
            backupConfig[key] = value;
            localStorage.setItem('backupConfig', JSON.stringify(backupConfig));
            
            if (key === 'enabled') {
                this.updateStatus(value ? 'idle' : 'disabled');
            }
        },
        
        updateServersList: function() {
            const serversList = document.getElementById('servers-list');
            if (!serversList) return;
            
            serversList.innerHTML = backupConfig.remoteServers.map((server, index) => `
                <div class="server-item">
                    <div class="server-info">
                        <div class="server-name">${server.name}</div>
                        <div class="server-status ${server.status || 'disconnected'}">${server.status || 'Unknown'}</div>
                    </div>
                    <div class="server-details">
                        ${server.type}: ${server.host}:${server.port} | ${server.path}
                    </div>
                    <div class="server-actions">
                        <button class="btn-icon" onclick="BackupSystem.testServer(${index})" title="Test Connection">
                            <i class="fas fa-plug"></i>
                        </button>
                        <button class="btn-icon" onclick="BackupSystem.editServer(${index})" title="Edit">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn-icon" onclick="BackupSystem.removeServer(${index})" title="Remove">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            `).join('');
        },
        
        showAddServerDialog: function() {
            const modal = document.createElement('div');
            modal.className = 'modal-overlay';
            modal.innerHTML = `
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Add Remote Backup Server</h3>
                        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">&times;</button>
                    </div>
                    <form id="add-server-form">
                        <div class="form-group">
                            <label>Server Name:</label>
                            <input type="text" id="server-name" required placeholder="Backup Server 1">
                        </div>
                        <div class="form-group">
                            <label>Server Type:</label>
                            <select id="server-type">
                                <option value="ftp">FTP</option>
                                <option value="sftp">SFTP</option>
                                <option value="scp">SCP</option>
                                <option value="rsync">Rsync</option>
                                <option value="s3">Amazon S3</option>
                                <option value="azure">Azure Blob</option>
                                <option value="gcp">Google Cloud</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Host/IP Address:</label>
                            <input type="text" id="server-host" required placeholder="192.168.1.100">
                        </div>
                        <div class="form-group">
                            <label>Port:</label>
                            <input type="number" id="server-port" value="22" min="1" max="65535">
                        </div>
                        <div class="form-group">
                            <label>Username:</label>
                            <input type="text" id="server-username" required>
                        </div>
                        <div class="form-group">
                            <label>Password:</label>
                            <input type="password" id="server-password">
                        </div>
                        <div class="form-group">
                            <label>Remote Path:</label>
                            <input type="text" id="server-path" placeholder="/backup/noctispro">
                        </div>
                        <div class="modal-actions">
                            <button type="button" class="btn-secondary" onclick="this.closest('.modal-overlay').remove()">Cancel</button>
                            <button type="submit" class="btn-primary">Add Server</button>
                        </div>
                    </form>
                </div>
            `;
            
            modal.querySelector('#add-server-form').addEventListener('submit', (e) => {
                e.preventDefault();
                this.addServer({
                    name: document.getElementById('server-name').value,
                    type: document.getElementById('server-type').value,
                    host: document.getElementById('server-host').value,
                    port: parseInt(document.getElementById('server-port').value),
                    username: document.getElementById('server-username').value,
                    password: document.getElementById('server-password').value,
                    path: document.getElementById('server-path').value,
                    status: 'disconnected'
                });
                modal.remove();
            });
            
            document.body.appendChild(modal);
        },
        
        addServer: function(server) {
            backupConfig.remoteServers.push(server);
            localStorage.setItem('backupConfig', JSON.stringify(backupConfig));
            this.updateServersList();
        },
        
        removeServer: function(index) {
            if (confirm('Are you sure you want to remove this backup server?')) {
                backupConfig.remoteServers.splice(index, 1);
                localStorage.setItem('backupConfig', JSON.stringify(backupConfig));
                this.updateServersList();
            }
        },
        
        testServer: async function(index) {
            const server = backupConfig.remoteServers[index];
            if (!server) return;
            
            server.status = 'testing';
            this.updateServersList();
            
            try {
                // Simulate connection test
                await new Promise(resolve => setTimeout(resolve, 2000));
                
                // Random success/failure for demo
                const success = Math.random() > 0.3;
                server.status = success ? 'connected' : 'disconnected';
                server.lastTest = new Date().toISOString();
                
                localStorage.setItem('backupConfig', JSON.stringify(backupConfig));
                this.updateServersList();
                
                if (success) {
                    this.showNotification('Connection test successful', 'success');
                } else {
                    this.showNotification('Connection test failed', 'error');
                }
                
            } catch (error) {
                server.status = 'disconnected';
                this.updateServersList();
                this.showNotification('Connection test failed: ' + error.message, 'error');
            }
        },
        
        testConnections: async function() {
            const button = document.getElementById('test-connection');
            button.disabled = true;
            button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Testing...';
            
            for (let i = 0; i < backupConfig.remoteServers.length; i++) {
                await this.testServer(i);
                await new Promise(resolve => setTimeout(resolve, 500)); // Small delay between tests
            }
            
            button.disabled = false;
            button.innerHTML = '<i class="fas fa-network-wired"></i> Test Connections';
        },
        
        startManualBackup: async function() {
            if (isBackupRunning) {
                this.showNotification('Backup already in progress', 'warning');
                return;
            }
            
            isBackupRunning = true;
            this.updateStatus('running');
            this.showProgress();
            
            try {
                await this.performBackup();
                this.updateStatus('success');
                this.showNotification('Backup completed successfully', 'success');
            } catch (error) {
                this.updateStatus('error');
                this.showNotification('Backup failed: ' + error.message, 'error');
            } finally {
                isBackupRunning = false;
                this.hideProgress();
                this.loadBackupHistory();
            }
        },
        
        performBackup: async function() {
            const steps = [
                'Preparing backup...',
                'Backing up database...',
                'Backing up DICOM files...',
                'Backing up configuration...',
                'Compressing backup...',
                'Uploading to remote servers...',
                'Verifying backup integrity...',
                'Cleaning up old backups...'
            ];
            
            for (let i = 0; i < steps.length; i++) {
                this.updateProgress(steps[i], (i + 1) / steps.length * 100, `Step ${i + 1} of ${steps.length}`);
                
                // Simulate work
                await new Promise(resolve => setTimeout(resolve, 1000 + Math.random() * 2000));
                
                // Simulate potential failure
                if (Math.random() < 0.05) { // 5% chance of failure
                    throw new Error(`Failed at: ${steps[i]}`);
                }
            }
            
            // Add to history
            const backupRecord = {
                id: Date.now(),
                date: new Date().toISOString(),
                type: 'manual',
                status: 'success',
                size: Math.floor(Math.random() * 1000 + 100), // MB
                duration: Math.floor(Math.random() * 300 + 60), // seconds
                servers: backupConfig.remoteServers.filter(s => s.status === 'connected').length,
                files: Math.floor(Math.random() * 10000 + 1000)
            };
            
            backupHistory.unshift(backupRecord);
            localStorage.setItem('backupHistory', JSON.stringify(backupHistory.slice(0, 50))); // Keep last 50
        },
        
        showProgress: function() {
            const progressEl = document.getElementById('backup-progress');
            progressEl.style.display = 'block';
        },
        
        hideProgress: function() {
            const progressEl = document.getElementById('backup-progress');
            progressEl.style.display = 'none';
        },
        
        updateProgress: function(text, percentage, operation) {
            document.getElementById('progress-text').textContent = text;
            document.getElementById('progress-percentage').textContent = Math.round(percentage) + '%';
            document.getElementById('progress-fill').style.width = percentage + '%';
            document.getElementById('current-operation').textContent = operation;
            
            // Update size (simulated)
            const size = Math.floor(percentage * 10);
            document.getElementById('backup-size').textContent = `Size: ${size} MB`;
        },
        
        updateStatus: function(status) {
            const indicator = document.getElementById('backup-status-indicator');
            const text = document.getElementById('backup-status-text');
            
            indicator.className = `status-indicator ${status}`;
            
            const statusTexts = {
                idle: 'Idle',
                running: 'Backup Running',
                success: 'Last Backup: Success',
                error: 'Last Backup: Failed',
                disabled: 'Disabled'
            };
            
            text.textContent = statusTexts[status] || status;
        },
        
        loadBackupHistory: function() {
            const saved = localStorage.getItem('backupHistory');
            if (saved) {
                backupHistory = JSON.parse(saved);
            }
            
            this.updateHistoryList();
        },
        
        updateHistoryList: function() {
            const historyList = document.getElementById('backup-history-list');
            if (!historyList) return;
            
            if (backupHistory.length === 0) {
                historyList.innerHTML = '<div class="history-item">No backup history available</div>';
                return;
            }
            
            historyList.innerHTML = backupHistory.slice(0, 10).map(backup => `
                <div class="history-item">
                    <div class="history-header">
                        <div class="backup-date">${new Date(backup.date).toLocaleString()}</div>
                        <div class="backup-result ${backup.status}">${backup.status}</div>
                    </div>
                    <div class="history-details">
                        ${backup.type} backup | ${backup.size} MB | ${backup.duration}s | ${backup.servers} servers | ${backup.files} files
                    </div>
                </div>
            `).join('');
        },
        
        refreshHistory: function() {
            this.loadBackupHistory();
            this.showNotification('History refreshed', 'info');
        },
        
        exportHistory: function() {
            const data = {
                exported: new Date().toISOString(),
                config: backupConfig,
                history: backupHistory
            };
            
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `backup_log_${Date.now()}.json`;
            a.click();
            URL.revokeObjectURL(url);
        },
        
        showRestoreDialog: function() {
            // Implementation for restore dialog
            this.showNotification('Restore functionality coming soon', 'info');
        },
        
        startScheduler: function() {
            // Check every minute if backup should run
            setInterval(() => {
                if (backupConfig.enabled && !isBackupRunning) {
                    this.checkSchedule();
                }
            }, 60000);
        },
        
        checkSchedule: function() {
            const now = new Date();
            const [hours, minutes] = backupConfig.time.split(':').map(Number);
            
            if (now.getHours() === hours && now.getMinutes() === minutes) {
                const lastBackup = backupHistory[0];
                const shouldRun = this.shouldRunScheduledBackup(lastBackup);
                
                if (shouldRun) {
                    this.startManualBackup();
                }
            }
        },
        
        shouldRunScheduledBackup: function(lastBackup) {
            if (!lastBackup) return true;
            
            const lastBackupDate = new Date(lastBackup.date);
            const now = new Date();
            const hoursDiff = (now - lastBackupDate) / (1000 * 60 * 60);
            
            switch (backupConfig.frequency) {
                case 'hourly': return hoursDiff >= 1;
                case 'daily': return hoursDiff >= 24;
                case 'weekly': return hoursDiff >= 168;
                case 'monthly': return hoursDiff >= 720;
                default: return false;
            }
        },
        
        showNotification: function(message, type = 'info') {
            const notification = document.createElement('div');
            notification.className = `backup-notification ${type}`;
            notification.innerHTML = `
                <div class="notification-content">
                    <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>
                    <span>${message}</span>
                </div>
            `;
            
            const style = document.createElement('style');
            style.textContent = `
                .backup-notification {
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    padding: 12px 16px;
                    border-radius: 6px;
                    z-index: 10001;
                    font-size: 12px;
                    animation: slideIn 0.3s ease;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.2);
                }
                .backup-notification.success { background: var(--success-color, #00ff88); color: #000; }
                .backup-notification.error { background: var(--danger-color, #ff4444); color: #fff; }
                .backup-notification.warning { background: var(--warning-color, #ffaa00); color: #000; }
                .backup-notification.info { background: var(--accent-color, #00d4ff); color: #000; }
                .notification-content {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }
            `;
            
            document.head.appendChild(style);
            document.body.appendChild(notification);
            
            setTimeout(() => {
                notification.remove();
                style.remove();
            }, 4000);
        }
    };
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => BackupSystem.init());
    } else {
        BackupSystem.init();
    }
    
})();