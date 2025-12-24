/**
 * Masterpiece 3D Bone Reconstruction Module
 * Advanced Three.js implementation for 3D bone reconstruction in DICOM viewer
 */

// Simple OrbitControls implementation for Three.js
THREE.OrbitControls = function(object, domElement) {
    this.object = object;
    this.domElement = domElement || document;
    this.target = new THREE.Vector3();
    
    // Configuration
    this.enableDamping = false;
    this.dampingFactor = 0.25;
    this.minDistance = 0;
    this.maxDistance = Infinity;
    this.maxPolarAngle = Math.PI;
    this.autoRotate = false;
    this.autoRotateSpeed = 2.0;
    this.zoomSpeed = 1.0;
    this.rotateSpeed = 1.0;
    this.panSpeed = 1.0;
    
    // Internal state
    this.spherical = new THREE.Spherical();
    this.sphericalDelta = new THREE.Spherical();
    this.scale = 1;
    this.panOffset = new THREE.Vector3();
    
    // Mouse state
    this.rotateStart = new THREE.Vector2();
    this.rotateEnd = new THREE.Vector2();
    this.rotateDelta = new THREE.Vector2();
    
    this.panStart = new THREE.Vector2();
    this.panEnd = new THREE.Vector2();
    this.panDelta = new THREE.Vector2();

    const STATE = { NONE: -1, ROTATE: 0, PAN: 1 };
    let state = STATE.NONE;

    // Event handlers
    const scope = this;

    function getElement() {
        return scope.domElement === document ? scope.domElement.body : scope.domElement;
    }

    function onContextMenu(event) {
        event.preventDefault();
    }

    function onMouseDown(event) {
        event.preventDefault();
        if (event.button === 0) {
            state = STATE.ROTATE;
            scope.rotateStart.set(event.clientX, event.clientY);
        } else if (event.button === 2) {
            state = STATE.PAN;
            scope.panStart.set(event.clientX, event.clientY);
        } else {
            state = STATE.NONE;
        }
        document.addEventListener('mousemove', onMouseMove, { passive: false });
        document.addEventListener('mouseup', onMouseUp, { passive: false });
    }

    function onMouseMove(event) {
        event.preventDefault();
        const element = getElement();
        if (state === STATE.ROTATE) {
            scope.rotateEnd.set(event.clientX, event.clientY);
            scope.rotateDelta.subVectors(scope.rotateEnd, scope.rotateStart).multiplyScalar(scope.rotateSpeed);
            scope.rotateLeft(2 * Math.PI * scope.rotateDelta.x / element.clientHeight);
            scope.rotateUp(2 * Math.PI * scope.rotateDelta.y / element.clientHeight);
            scope.rotateStart.copy(scope.rotateEnd);
        } else if (state === STATE.PAN) {
            scope.panEnd.set(event.clientX, event.clientY);
            scope.panDelta.subVectors(scope.panEnd, scope.panStart).multiplyScalar(scope.panSpeed);
            scope.pan(scope.panDelta.x, scope.panDelta.y);
            scope.panStart.copy(scope.panEnd);
        }
        scope.update();
    }

    function onMouseUp(event) {
        event.preventDefault();
        state = STATE.NONE;
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
    }

    function onMouseWheel(event) {
        event.preventDefault();
        if (event.deltaY < 0) {
            scope.dollyIn(scope.getZoomScale());
        } else if (event.deltaY > 0) {
            scope.dollyOut(scope.getZoomScale());
        }
        scope.update();
    }

    // Touch: 1 finger rotate, 2 finger pinch zoom + pan
    let touchStartDist = 0;
    let touchStartMid = null;
    function touchDistance(t0, t1) {
        const dx = t0.clientX - t1.clientX;
        const dy = t0.clientY - t1.clientY;
        return Math.sqrt(dx * dx + dy * dy);
    }
    function touchMidpoint(t0, t1) {
        return { x: (t0.clientX + t1.clientX) / 2, y: (t0.clientY + t1.clientY) / 2 };
    }
    function onTouchStart(event) {
        if (!event.touches) return;
        if (event.touches.length === 1) {
            state = STATE.ROTATE;
            scope.rotateStart.set(event.touches[0].clientX, event.touches[0].clientY);
        } else if (event.touches.length === 2) {
            state = STATE.PAN;
            touchStartDist = touchDistance(event.touches[0], event.touches[1]);
            touchStartMid = touchMidpoint(event.touches[0], event.touches[1]);
        }
    }
    function onTouchMove(event) {
        if (!event.touches) return;
        event.preventDefault();
        const element = getElement();
        if (event.touches.length === 1 && state === STATE.ROTATE) {
            scope.rotateEnd.set(event.touches[0].clientX, event.touches[0].clientY);
            scope.rotateDelta.subVectors(scope.rotateEnd, scope.rotateStart).multiplyScalar(scope.rotateSpeed);
            scope.rotateLeft(2 * Math.PI * scope.rotateDelta.x / element.clientHeight);
            scope.rotateUp(2 * Math.PI * scope.rotateDelta.y / element.clientHeight);
            scope.rotateStart.copy(scope.rotateEnd);
        } else if (event.touches.length === 2) {
            // dolly
            const dist = touchDistance(event.touches[0], event.touches[1]);
            if (touchStartDist > 0) {
                const scale = dist / touchStartDist;
                if (scale > 1) scope.dollyIn(Math.pow(0.95, scope.zoomSpeed) / scale);
                if (scale < 1) scope.dollyOut(Math.pow(0.95, scope.zoomSpeed) * (1 / Math.max(scale, 0.001)));
            }
            touchStartDist = dist;
            // pan by midpoint movement
            const mid = touchMidpoint(event.touches[0], event.touches[1]);
            if (touchStartMid) {
                scope.pan(mid.x - touchStartMid.x, mid.y - touchStartMid.y);
            }
            touchStartMid = mid;
        }
        scope.update();
    }
    function onTouchEnd() {
        state = STATE.NONE;
        touchStartDist = 0;
        touchStartMid = null;
    }

    this.domElement.addEventListener('contextmenu', onContextMenu);
    this.domElement.addEventListener('mousedown', onMouseDown, { passive: false });
    this.domElement.addEventListener('wheel', onMouseWheel, { passive: false });
    this.domElement.addEventListener('touchstart', onTouchStart, { passive: true });
    this.domElement.addEventListener('touchmove', onTouchMove, { passive: false });
    this.domElement.addEventListener('touchend', onTouchEnd, { passive: true });
    
    this.rotateLeft = function(angle) {
        this.sphericalDelta.theta -= angle;
    };
    
    this.rotateUp = function(angle) {
        this.sphericalDelta.phi -= angle;
    };

    this.pan = function(deltaX, deltaY) {
        const element = getElement();
        const offset = new THREE.Vector3();
        offset.copy(this.object.position).sub(this.target);

        // targetDistance accounts for perspective projection.
        const targetDistance = offset.length() * Math.tan((this.object.fov / 2) * Math.PI / 180.0);
        const panX = (2 * deltaX * targetDistance / element.clientHeight);
        const panY = (2 * deltaY * targetDistance / element.clientHeight);

        const panLeft = new THREE.Vector3();
        const panUp = new THREE.Vector3();
        const te = this.object.matrix.elements;
        // X axis
        panLeft.set(te[0], te[1], te[2]).multiplyScalar(-panX);
        // Y axis
        panUp.set(te[4], te[5], te[6]).multiplyScalar(panY);
        this.panOffset.add(panLeft);
        this.panOffset.add(panUp);
    };
    
    this.dollyIn = function(dollyScale) {
        this.scale /= dollyScale;
    };
    
    this.dollyOut = function(dollyScale) {
        this.scale *= dollyScale;
    };
    
    this.getZoomScale = function() {
        return Math.pow(0.95, this.zoomSpeed);
    };
    
    this.update = function() {
        const offset = new THREE.Vector3();
        const quat = new THREE.Quaternion().setFromUnitVectors(this.object.up, new THREE.Vector3(0, 1, 0));
        const quatInverse = quat.clone().invert();
        
        offset.copy(this.object.position).sub(this.target);
        offset.applyQuaternion(quat);
        
        this.spherical.setFromVector3(offset);
        
        if (this.autoRotate) {
            this.rotateLeft(this.getAutoRotationAngle());
        }
        
        this.spherical.theta += this.sphericalDelta.theta;
        this.spherical.phi += this.sphericalDelta.phi;
        
        this.spherical.phi = Math.max(0.000001, Math.min(Math.PI - 0.000001, this.spherical.phi));
        this.spherical.radius *= this.scale;
        this.spherical.radius = Math.max(this.minDistance, Math.min(this.maxDistance, this.spherical.radius));
        
        this.target.add(this.panOffset);
        
        offset.setFromSpherical(this.spherical);
        offset.applyQuaternion(quatInverse);
        
        this.object.position.copy(this.target).add(offset);
        this.object.lookAt(this.target);
        
        if (this.enableDamping) {
            this.sphericalDelta.theta *= (1 - this.dampingFactor);
            this.sphericalDelta.phi *= (1 - this.dampingFactor);
        } else {
            this.sphericalDelta.set(0, 0, 0);
        }
        
        this.scale = 1;
        this.panOffset.set(0, 0, 0);
        
        return false;
    };
    
    this.getAutoRotationAngle = function() {
        return 2 * Math.PI / 60 / 60 * this.autoRotateSpeed;
    };
    
    this.dispose = function() {
        this.domElement.removeEventListener('contextmenu', onContextMenu);
        this.domElement.removeEventListener('mousedown', onMouseDown);
        this.domElement.removeEventListener('wheel', onMouseWheel);
        this.domElement.removeEventListener('touchstart', onTouchStart);
        this.domElement.removeEventListener('touchmove', onTouchMove);
        this.domElement.removeEventListener('touchend', onTouchEnd);
    };
    
    this.update();
};

class MasterpieceBoneReconstruction3D {
    constructor(canvasId, options = {}) {
        this.canvasId = canvasId;
        this.canvas = document.getElementById(canvasId);
        this.options = {
            threshold: 200,
            opacity: 0.8,
            autoRotate: false,
            wireframe: false,
            smoothShading: true,
            backgroundColor: 0x000000,
            enableShadows: true,
            enableLighting: true,
            ...options
        };
        
        // Three.js components
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.controls = null;
        this.boneMesh = null;
        this.animationId = null;
        
        // Lighting
        this.lights = [];
        
        // Volume data
        this.volumeData = null;
        this.volumeTexture = null;
        
        // Materials
        this.boneMaterial = null;
        this.wireframeMaterial = null;
        
        // Performance monitoring
        this.stats = null;
        this.performanceMonitor = {
            frameCount: 0,
            lastTime: Date.now(),
            fps: 0
        };
        
        this.init();
    }
    
    init() {
        try {
            this.setupScene();
            this.setupCamera();
            this.setupRenderer();
            this.setupControls();
            this.setupLighting();
            this.setupEventListeners();
            this.setupPerformanceMonitor();
            this.animate();
            
            console.log('✅ Masterpiece 3D reconstruction initialized successfully');
        } catch (error) {
            console.error('❌ Error initializing 3D reconstruction:', error);
            this.showError('Failed to initialize 3D reconstruction');
        }
    }
    
    setupScene() {
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(this.options.backgroundColor);
        
        // Add fog for depth perception
        this.scene.fog = new THREE.Fog(this.options.backgroundColor, 100, 1000);
        
        // Add coordinate system helper (optional)
        const axesHelper = new THREE.AxesHelper(50);
        axesHelper.visible = false; // Hidden by default
        this.scene.add(axesHelper);
        this.axesHelper = axesHelper;
        
        // Add grid helper
        const gridHelper = new THREE.GridHelper(200, 20, 0x444444, 0x222222);
        gridHelper.visible = false;
        this.scene.add(gridHelper);
        this.gridHelper = gridHelper;
    }
    
    setupCamera() {
        const aspect = this.canvas.clientWidth / this.canvas.clientHeight;
        this.camera = new THREE.PerspectiveCamera(75, aspect, 0.1, 2000);
        this.camera.position.set(200, 200, 200);
        this.camera.lookAt(0, 0, 0);
    }
    
    setupRenderer() {
        this.renderer = new THREE.WebGLRenderer({
            canvas: this.canvas,
            antialias: true,
            alpha: true,
            preserveDrawingBuffer: true,
            powerPreference: "high-performance"
        });
        
        this.renderer.setSize(this.canvas.clientWidth, this.canvas.clientHeight);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        
        if (this.options.enableShadows) {
            this.renderer.shadowMap.enabled = true;
            this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        }
        
        this.renderer.outputEncoding = THREE.sRGBEncoding;
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.2;
    }
    
    setupControls() {
        // Enhanced orbit controls with constraints
        this.controls = new THREE.OrbitControls(this.camera, this.canvas);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.05;
        this.controls.screenSpacePanning = false;
        this.controls.minDistance = 50;
        this.controls.maxDistance = 800;
        this.controls.maxPolarAngle = Math.PI;
        
        // Add smooth zoom
        this.controls.zoomSpeed = 0.5;
        this.controls.rotateSpeed = 0.5;
        this.controls.panSpeed = 0.8;
        
        // Auto-rotate settings
        this.controls.autoRotate = this.options.autoRotate;
        this.controls.autoRotateSpeed = 2.0;
    }
    
    setupLighting() {
        // Ambient light for overall illumination
        const ambientLight = new THREE.AmbientLight(0x404040, 0.4);
        this.scene.add(ambientLight);
        this.lights.push(ambientLight);
        
        // Main directional light (key light)
        const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
        directionalLight.position.set(100, 100, 100);
        if (this.options.enableShadows) {
            directionalLight.castShadow = true;
            directionalLight.shadow.mapSize.width = 2048;
            directionalLight.shadow.mapSize.height = 2048;
            directionalLight.shadow.camera.near = 0.5;
            directionalLight.shadow.camera.far = 500;
            directionalLight.shadow.camera.left = -100;
            directionalLight.shadow.camera.right = 100;
            directionalLight.shadow.camera.top = 100;
            directionalLight.shadow.camera.bottom = -100;
        }
        this.scene.add(directionalLight);
        this.lights.push(directionalLight);
        
        // Fill light (softer, from opposite side)
        const fillLight = new THREE.DirectionalLight(0xffffff, 0.3);
        fillLight.position.set(-50, 50, -50);
        this.scene.add(fillLight);
        this.lights.push(fillLight);
        
        // Rim light (for edge definition)
        const rimLight = new THREE.DirectionalLight(0x4080ff, 0.2);
        rimLight.position.set(0, -100, -100);
        this.scene.add(rimLight);
        this.lights.push(rimLight);
        
        // Point light for additional depth
        const pointLight = new THREE.PointLight(0xffffff, 0.5, 300);
        pointLight.position.set(0, 100, 0);
        this.scene.add(pointLight);
        this.lights.push(pointLight);
    }
    
    setupEventListeners() {
        // Handle canvas resize
        window.addEventListener('resize', this.onWindowResize.bind(this));
        
        // Handle canvas container resize
        const resizeObserver = new ResizeObserver(this.onWindowResize.bind(this));
        resizeObserver.observe(this.canvas.parentElement);
        
        // Mouse events for interaction feedback
        this.canvas.addEventListener('mousedown', this.onMouseDown.bind(this));
        this.canvas.addEventListener('contextmenu', this.onContextMenu.bind(this));
        // Wheel + touch are handled by OrbitControls for smooth zoom/pan/rotate
    }
    
    setupPerformanceMonitor() {
        // Initialize performance monitoring
        this.performanceMonitor.lastTime = Date.now();
    }
    
    onWindowResize() {
        if (!this.canvas.parentElement) return;
        
        const width = this.canvas.parentElement.clientWidth;
        const height = this.canvas.parentElement.clientHeight;
        
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        
        this.renderer.setSize(width, height);
        
        console.log(`📐 3D canvas resized to ${width}x${height}`);
    }
    
    onMouseDown(event) {
        // Provide visual feedback on interaction
        this.canvas.style.cursor = 'grabbing';
        
        const onMouseUp = () => {
            this.canvas.style.cursor = 'grab';
            document.removeEventListener('mouseup', onMouseUp);
        };
        
        document.addEventListener('mouseup', onMouseUp);
    }
    
    // Wheel/touch interaction is provided by OrbitControls.
    
    onContextMenu(event) {
        event.preventDefault();
        this.showContextMenu(event);
    }
    
    showContextMenu(event) {
        // Create enhanced context menu for 3D operations
        const menu = document.createElement('div');
        menu.style.cssText = `
            position: fixed;
            left: ${event.clientX}px;
            top: ${event.clientY}px;
            background: rgba(0,0,0,0.9);
            border-radius: 8px;
            padding: 12px;
            z-index: 10000;
            color: white;
            font-size: 13px;
            backdrop-filter: blur(15px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
            min-width: 180px;
        `;
        
        const options = [
            { label: '🔄 Reset View', action: () => this.resetView() },
            { label: '🔲 Toggle Wireframe', action: () => this.toggleWireframe() },
            { label: '🔄 Auto Rotate', action: () => this.toggleAutoRotate() },
            { label: '💡 Toggle Lighting', action: () => this.toggleLighting() },
            { label: '📐 Show Grid', action: () => this.toggleGrid() },
            { label: '📊 Show Axes', action: () => this.toggleAxes() },
            { label: '📁 Export STL', action: () => this.exportSTL() },
            { label: '📷 Screenshot', action: () => this.takeScreenshot() },
            { label: '📈 Show Stats', action: () => this.toggleStats() }
        ];
        
        options.forEach(option => {
            const item = document.createElement('div');
            item.textContent = option.label;
            item.style.cssText = `
                padding: 8px 12px; 
                cursor: pointer; 
                border-radius: 4px;
                transition: background 0.2s ease;
            `;
            item.onmouseover = () => item.style.background = 'rgba(0, 120, 212, 0.3)';
            item.onmouseout = () => item.style.background = 'transparent';
            item.onclick = () => {
                option.action();
                document.body.removeChild(menu);
            };
            menu.appendChild(item);
        });
        
        document.body.appendChild(menu);
        
        // Remove menu on click outside
        setTimeout(() => {
            const removeMenu = (e) => {
                if (!menu.contains(e.target)) {
                    if (document.body.contains(menu)) {
                        document.body.removeChild(menu);
                    }
                    document.removeEventListener('click', removeMenu);
                }
            };
            document.addEventListener('click', removeMenu);
        }, 100);
    }
    
    async loadVolumeData(seriesId, threshold = null) {
        try {
            this.showLoadingIndicator();
            
            threshold = threshold || this.options.threshold;
            
            console.log(`🔄 Loading bone reconstruction for series ${seriesId} with threshold ${threshold}`);
            
            // Fetch bone reconstruction data from Django backend
            const response = await fetch(`/dicom-viewer/api/series/${seriesId}/bone/?threshold=${threshold}&smooth=${this.options.smoothShading}`, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                }
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.error) {
                throw new Error(data.error);
            }
            
            this.volumeData = data;
            await this.createBoneMesh(data.mesh_data);
            this.updateStatisticsDisplay(data.statistics);
            
            this.hideLoadingIndicator();
            
            console.log('✅ Bone reconstruction loaded successfully');
            this.showToast('3D reconstruction generated successfully', 'success');
            
        } catch (error) {
            console.error('❌ Error loading volume data:', error);
            this.showError(`Failed to load bone reconstruction: ${error.message}`);
            this.hideLoadingIndicator();
        }
    }
    
    async createBoneMesh(meshData) {
        // Remove existing bone mesh
        if (this.boneMesh) {
            this.scene.remove(this.boneMesh);
            this.boneMesh.geometry.dispose();
            this.boneMesh.material.dispose();
        }
        
        if (!meshData || !meshData.vertices || !meshData.faces) {
            console.warn('⚠️ Invalid mesh data received');
            this.renderPlaceholderBone();
            return;
        }
        
        try {
            // Create geometry from mesh data
            const geometry = new THREE.BufferGeometry();
            
            // Convert vertices and faces to Three.js format.
            // Backend vertices are in (z, y, x) voxel order.
            //
            // For a "professional" initial view we want the long (slice) axis to be vertical (Y-up),
            // similar to how reformats are displayed with superior at the top.
            // So we map:
            // - x_voxel -> X
            // - z_voxel -> Y (up), with a flip so superior appears "up" by default
            // - y_voxel -> Z
            const srcVerts = Array.isArray(meshData.vertices) ? meshData.vertices : [];
            const vertices = new Float32Array(srcVerts.length * 3);
            for (let i = 0; i < srcVerts.length; i++) {
                const v = srcVerts[i] || [0, 0, 0];
                const z = Number(v[0]) || 0;
                const y = Number(v[1]) || 0;
                const x = Number(v[2]) || 0;
                vertices[i * 3] = x;
                vertices[i * 3 + 1] = -z; // flip to make initial orientation upright (superior towards +Y)
                vertices[i * 3 + 2] = y;
            }
            const indices = new Uint32Array(meshData.faces.flat());
            
            geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
            geometry.setIndex(new THREE.BufferAttribute(indices, 1));
            
            // Compute normals for proper lighting
            geometry.computeVertexNormals();
            
            // Compute bounding box and center the geometry
            geometry.computeBoundingBox();
            const center = new THREE.Vector3();
            geometry.boundingBox.getCenter(center);
            geometry.translate(-center.x, -center.y, -center.z);
            
            // Create enhanced bone material
            await this.createBoneMaterial();
            
            // Create mesh
            this.boneMesh = new THREE.Mesh(geometry, this.boneMaterial);
            this.boneMesh.castShadow = this.options.enableShadows;
            this.boneMesh.receiveShadow = this.options.enableShadows;
            
            // Add to scene
            this.scene.add(this.boneMesh);
            
            // Adjust camera to fit the model
            this.fitCameraToModel();
            
            console.log(`✅ Bone mesh created with ${meshData.vertex_count} vertices and ${meshData.face_count} faces`);
            
        } catch (error) {
            console.error('❌ Error creating bone mesh:', error);
            this.renderPlaceholderBone();
        }
    }
    
    async createBoneMaterial() {
        // Create realistic bone material with enhanced properties
        this.boneMaterial = new THREE.MeshPhongMaterial({
            color: 0xf5f5dc, // Bone color (beige)
            shininess: 30,
            opacity: this.options.opacity,
            transparent: this.options.opacity < 1.0,
            side: THREE.DoubleSide,
            flatShading: !this.options.smoothShading
        });
        
        // Create wireframe material
        this.wireframeMaterial = new THREE.MeshBasicMaterial({
            color: 0x00ff00,
            wireframe: true,
            opacity: 0.8,
            transparent: true
        });
        
        // Add enhanced bone texture
        await this.loadBoneTexture();
    }
    
    async loadBoneTexture() {
        try {
            // Create a procedural bone texture with enhanced detail
            const canvas = document.createElement('canvas');
            canvas.width = 1024;
            canvas.height = 1024;
            const ctx = canvas.getContext('2d');
            
            // Create bone-like texture with multiple layers
            this.createBoneTextureLayer(ctx, canvas.width, canvas.height);
            
            // Create texture
            const texture = new THREE.CanvasTexture(canvas);
            texture.wrapS = THREE.RepeatWrapping;
            texture.wrapT = THREE.RepeatWrapping;
            texture.repeat.set(2, 2);
            texture.generateMipmaps = true;
            texture.minFilter = THREE.LinearMipmapLinearFilter;
            texture.magFilter = THREE.LinearFilter;
            
            this.boneMaterial.map = texture;
            this.boneMaterial.needsUpdate = true;
            
            // Create normal map for enhanced surface detail
            this.createBoneNormalMap();
            
        } catch (error) {
            console.warn('⚠️ Failed to create bone texture:', error);
        }
    }
    
    createBoneTextureLayer(ctx, width, height) {
        // Base gradient
        const gradient = ctx.createRadialGradient(width/2, height/2, 0, width/2, height/2, width/2);
        gradient.addColorStop(0, '#ffffff');
        gradient.addColorStop(0.3, '#f8f8f0');
        gradient.addColorStop(0.6, '#f0f0e8');
        gradient.addColorStop(1, '#e8e8e0');
        
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, width, height);
        
        // Add bone-like patterns
        ctx.globalCompositeOperation = 'overlay';
        
        // Create fibrous patterns
        for (let i = 0; i < 50; i++) {
            ctx.beginPath();
            ctx.strokeStyle = `rgba(220, 220, 200, ${Math.random() * 0.3})`;
            ctx.lineWidth = Math.random() * 3 + 1;
            ctx.moveTo(Math.random() * width, Math.random() * height);
            ctx.lineTo(Math.random() * width, Math.random() * height);
            ctx.stroke();
        }
        
        // Add noise for realistic texture
        const imageData = ctx.getImageData(0, 0, width, height);
        const data = imageData.data;
        
        for (let i = 0; i < data.length; i += 4) {
            const noise = (Math.random() - 0.5) * 15;
            data[i] = Math.max(0, Math.min(255, data[i] + noise));     // R
            data[i + 1] = Math.max(0, Math.min(255, data[i + 1] + noise)); // G
            data[i + 2] = Math.max(0, Math.min(255, data[i + 2] + noise)); // B
        }
        
        ctx.putImageData(imageData, 0, 0);
        ctx.globalCompositeOperation = 'source-over';
    }
    
    createBoneNormalMap() {
        // Create normal map for enhanced surface detail
        const canvas = document.createElement('canvas');
        canvas.width = 512;
        canvas.height = 512;
        const ctx = canvas.getContext('2d');
        
        // Generate normal map data
        const imageData = ctx.createImageData(canvas.width, canvas.height);
        const data = imageData.data;
        
        for (let i = 0; i < data.length; i += 4) {
            // Generate normal vectors (simplified)
            data[i] = 128 + Math.random() * 20 - 10;     // R (X normal)
            data[i + 1] = 128 + Math.random() * 20 - 10; // G (Y normal)
            data[i + 2] = 255;                           // B (Z normal)
            data[i + 3] = 255;                           // A
        }
        
        ctx.putImageData(imageData, 0, 0);
        
        const normalTexture = new THREE.CanvasTexture(canvas);
        normalTexture.wrapS = THREE.RepeatWrapping;
        normalTexture.wrapT = THREE.RepeatWrapping;
        normalTexture.repeat.set(2, 2);
        
        this.boneMaterial.normalMap = normalTexture;
        this.boneMaterial.normalScale = new THREE.Vector2(0.5, 0.5);
        this.boneMaterial.needsUpdate = true;
    }
    
    renderPlaceholderBone() {
        // Render a placeholder when mesh data is not available
        const geometry = new THREE.BoxGeometry(50, 150, 30);
        const material = new THREE.MeshPhongMaterial({
            color: 0xf5f5dc,
            opacity: this.options.opacity,
            transparent: true
        });
        
        this.boneMesh = new THREE.Mesh(geometry, material);
        this.scene.add(this.boneMesh);
        
        // Add text sprite for placeholder indication
        this.addPlaceholderText();
    }
    
    addPlaceholderText() {
        const canvas = document.createElement('canvas');
        canvas.width = 512;
        canvas.height = 256;
        const ctx = canvas.getContext('2d');
        
        ctx.fillStyle = 'rgba(0, 0, 0, 0.8)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        ctx.fillStyle = '#00d4ff';
        ctx.font = 'bold 32px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('3D Bone Reconstruction', canvas.width/2, canvas.height/2 - 20);
        
        ctx.fillStyle = '#ffffff';
        ctx.font = '20px Arial';
        ctx.fillText('Processing...', canvas.width/2, canvas.height/2 + 20);
        
        const texture = new THREE.CanvasTexture(canvas);
        const material = new THREE.SpriteMaterial({ map: texture });
        const sprite = new THREE.Sprite(material);
        sprite.scale.set(100, 50, 1);
        sprite.position.set(0, 100, 0);
        
        this.scene.add(sprite);
        this.placeholderSprite = sprite;
    }
    
    fitCameraToModel() {
        if (!this.boneMesh) return;
        
        const box = new THREE.Box3().setFromObject(this.boneMesh);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        
        // Calculate optimal camera distance
        const maxSize = Math.max(size.x, size.y, size.z);
        const distance = maxSize * 2.5;
        
        // Position camera for an upright, "clinical" first view:
        // look slightly down from the front, keeping Y as up.
        this.camera.up.set(0, 1, 0);
        this.camera.position.set(0, maxSize * 0.35, distance);
        this.camera.lookAt(center);
        
        // Update controls
        this.controls.target = center;
        this.controls.update();
        
        // Set zoom limits based on model size
        this.controls.minDistance = maxSize * 0.5;
        this.controls.maxDistance = maxSize * 8;
        
        // Optional: subtle ground plane for depth perception (looks more professional with shadows).
        try {
            if (!this.groundPlane) {
                const planeGeo = new THREE.PlaneGeometry(1, 1);
                const planeMat = this.options.enableShadows
                    ? new THREE.ShadowMaterial({ opacity: 0.18 })
                    : new THREE.MeshBasicMaterial({ color: 0x0a0a0a, transparent: true, opacity: 0.0 });
                this.groundPlane = new THREE.Mesh(planeGeo, planeMat);
                this.groundPlane.rotation.x = -Math.PI / 2;
                this.groundPlane.receiveShadow = !!this.options.enableShadows;
                this.scene.add(this.groundPlane);
            }
            const planeSize = maxSize * 4;
            this.groundPlane.scale.set(planeSize, planeSize, 1);
            this.groundPlane.position.set(center.x, center.y - (size.y / 2) - (maxSize * 0.08), center.z);
        } catch (_) { /* ignore */ }

        console.log(`📐 Camera fitted to model (size: ${maxSize.toFixed(1)})`);
    }
    
    animate() {
        this.animationId = requestAnimationFrame(this.animate.bind(this));
        
        // Update performance monitor
        this.updatePerformanceMonitor();
        
        // Auto rotation if enabled
        if (this.options.autoRotate && this.boneMesh) {
            this.boneMesh.rotation.y += 0.005;
        }
        
        // Update controls
        this.controls.update();
        
        // Render
        this.renderer.render(this.scene, this.camera);
    }
    
    updatePerformanceMonitor() {
        this.performanceMonitor.frameCount++;
        const currentTime = Date.now();
        const deltaTime = currentTime - this.performanceMonitor.lastTime;
        
        if (deltaTime >= 1000) { // Update FPS every second
            this.performanceMonitor.fps = Math.round((this.performanceMonitor.frameCount * 1000) / deltaTime);
            this.performanceMonitor.frameCount = 0;
            this.performanceMonitor.lastTime = currentTime;
            
            // Update FPS display if stats are visible
            if (this.statsVisible) {
                this.updateStatsDisplay();
            }
        }
    }
    
    updateStatisticsDisplay(statistics) {
        if (!statistics) return;
        
        // Update the UI with bone density statistics
        const event = new CustomEvent('boneStatisticsUpdate', {
            detail: statistics
        });
        document.dispatchEvent(event);
        
        console.log('📊 Bone statistics updated:', statistics);
    }
    
    // Public control methods
    
    setThreshold(threshold) {
        this.options.threshold = threshold;
        if (this.volumeData && this.volumeData.series_id) {
            this.loadVolumeData(this.volumeData.series_id, threshold);
        }
    }
    
    setOpacity(opacity) {
        this.options.opacity = opacity;
        if (this.boneMaterial) {
            this.boneMaterial.opacity = opacity;
            this.boneMaterial.transparent = opacity < 1.0;
            this.boneMaterial.needsUpdate = true;
        }
    }
    
    toggleWireframe() {
        if (!this.boneMesh) return;
        
        this.options.wireframe = !this.options.wireframe;
        
        if (this.options.wireframe) {
            this.boneMesh.material = this.wireframeMaterial;
        } else {
            this.boneMesh.material = this.boneMaterial;
        }
        
        this.showToast(`Wireframe ${this.options.wireframe ? 'enabled' : 'disabled'}`, 'info');
    }
    
    toggleAutoRotate() {
        this.options.autoRotate = !this.options.autoRotate;
        this.controls.autoRotate = this.options.autoRotate;
        
        this.showToast(`Auto rotation ${this.options.autoRotate ? 'enabled' : 'disabled'}`, 'info');
    }
    
    toggleLighting() {
        this.options.enableLighting = !this.options.enableLighting;
        
        this.lights.forEach(light => {
            light.visible = this.options.enableLighting;
        });
        
        this.showToast(`Lighting ${this.options.enableLighting ? 'enabled' : 'disabled'}`, 'info');
    }
    
    toggleGrid() {
        if (this.gridHelper) {
            this.gridHelper.visible = !this.gridHelper.visible;
            this.showToast(`Grid ${this.gridHelper.visible ? 'enabled' : 'disabled'}`, 'info');
        }
    }
    
    toggleAxes() {
        if (this.axesHelper) {
            this.axesHelper.visible = !this.axesHelper.visible;
            this.showToast(`Axes ${this.axesHelper.visible ? 'enabled' : 'disabled'}`, 'info');
        }
    }
    
    toggleStats() {
        this.statsVisible = !this.statsVisible;
        if (this.statsVisible) {
            this.showStatsDisplay();
        } else {
            this.hideStatsDisplay();
        }
    }
    
    resetView() {
        if (this.boneMesh) {
            this.boneMesh.rotation.set(0, 0, 0);
            this.fitCameraToModel();
            this.showToast('View reset', 'success');
        }
    }
    
    exportSTL() {
        if (!this.boneMesh) {
            this.showToast('No bone mesh to export', 'warning');
            return;
        }
        
        try {
            // Create STL exporter (simplified version)
            const geometry = this.boneMesh.geometry;
            const vertices = geometry.attributes.position.array;
            const indices = geometry.index ? geometry.index.array : null;
            
            let stlString = 'solid bone\n';
            
            if (indices) {
                for (let i = 0; i < indices.length; i += 3) {
                    const a = indices[i] * 3;
                    const b = indices[i + 1] * 3;
                    const c = indices[i + 2] * 3;
                    
                    // Calculate normal
                    const v1 = new THREE.Vector3(vertices[a], vertices[a + 1], vertices[a + 2]);
                    const v2 = new THREE.Vector3(vertices[b], vertices[b + 1], vertices[b + 2]);
                    const v3 = new THREE.Vector3(vertices[c], vertices[c + 1], vertices[c + 2]);
                    
                    const normal = new THREE.Vector3()
                        .subVectors(v2, v1)
                        .cross(new THREE.Vector3().subVectors(v3, v1))
                        .normalize();
                    
                    stlString += `  facet normal ${normal.x} ${normal.y} ${normal.z}\n`;
                    stlString += '    outer loop\n';
                    stlString += `      vertex ${v1.x} ${v1.y} ${v1.z}\n`;
                    stlString += `      vertex ${v2.x} ${v2.y} ${v2.z}\n`;
                    stlString += `      vertex ${v3.x} ${v3.y} ${v3.z}\n`;
                    stlString += '    endloop\n';
                    stlString += '  endfacet\n';
                }
            }
            
            stlString += 'endsolid bone\n';
            
            // Create download link
            const blob = new Blob([stlString], { type: 'application/octet-stream' });
            const url = URL.createObjectURL(blob);
            
            const link = document.createElement('a');
            link.href = url;
            link.download = `bone_reconstruction_${Date.now()}.stl`;
            link.click();
            
            URL.revokeObjectURL(url);
            
            this.showToast('STL file exported successfully', 'success');
            
        } catch (error) {
            console.error('Export failed:', error);
            this.showToast('Failed to export STL file', 'error');
        }
    }
    
    takeScreenshot() {
        try {
            // Render at higher resolution for screenshot
            const originalSize = this.renderer.getSize(new THREE.Vector2());
            const screenshotSize = { width: 1920, height: 1080 };
            
            this.renderer.setSize(screenshotSize.width, screenshotSize.height);
            this.camera.aspect = screenshotSize.width / screenshotSize.height;
            this.camera.updateProjectionMatrix();
            
            this.renderer.render(this.scene, this.camera);
            
            // Get image data
            const dataURL = this.canvas.toDataURL('image/png');
            
            // Restore original size
            this.renderer.setSize(originalSize.width, originalSize.height);
            this.camera.aspect = originalSize.width / originalSize.height;
            this.camera.updateProjectionMatrix();
            
            // Create download link
            const link = document.createElement('a');
            link.href = dataURL;
            link.download = `bone_reconstruction_${Date.now()}.png`;
            link.click();
            
            this.showToast('Screenshot saved', 'success');
            
        } catch (error) {
            console.error('Screenshot failed:', error);
            this.showToast('Failed to take screenshot', 'error');
        }
    }
    
    // Utility methods
    
    showLoadingIndicator() {
        if (this.loadingOverlay) return;
        
        this.loadingOverlay = document.createElement('div');
        this.loadingOverlay.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 14px;
            z-index: 1000;
            backdrop-filter: blur(5px);
        `;
        
        this.loadingOverlay.innerHTML = `
            <div style="text-align: center;">
                <div style="
                    border: 3px solid #333;
                    border-top: 3px solid #00d4ff;
                    border-radius: 50%;
                    width: 40px;
                    height: 40px;
                    animation: spin 1s linear infinite;
                    margin: 0 auto 15px;
                "></div>
                <div>Generating 3D bone reconstruction...</div>
                <div style="font-size: 12px; opacity: 0.7; margin-top: 5px;">
                    This may take a few moments
                </div>
            </div>
        `;
        
        this.canvas.parentElement.style.position = 'relative';
        this.canvas.parentElement.appendChild(this.loadingOverlay);
    }
    
    hideLoadingIndicator() {
        if (this.loadingOverlay) {
            this.loadingOverlay.remove();
            this.loadingOverlay = null;
        }
    }
    
    showError(message) {
        // Show error message overlay
        const errorOverlay = document.createElement('div');
        errorOverlay.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.9);
            display: flex;
            align-items: center;
            justify-content: center;
            color: #ff4444;
            font-size: 14px;
            z-index: 1000;
            text-align: center;
            padding: 20px;
        `;
        
        errorOverlay.innerHTML = `
            <div>
                <i class="fas fa-exclamation-triangle" style="font-size: 48px; margin-bottom: 15px;"></i>
                <div style="font-size: 16px; margin-bottom: 10px;">3D Reconstruction Error</div>
                <div>${message}</div>
                <button onclick="this.parentElement.parentElement.remove()" 
                        style="margin-top: 15px; padding: 8px 16px; background: #ff4444; color: white; border: none; border-radius: 4px; cursor: pointer;">
                    Close
                </button>
            </div>
        `;
        
        this.canvas.parentElement.appendChild(errorOverlay);
        
        setTimeout(() => {
            if (errorOverlay.parentElement) {
                errorOverlay.remove();
            }
        }, 10000);
    }
    
    showStatsDisplay() {
        if (this.statsDisplay) return;
        
        this.statsDisplay = document.createElement('div');
        this.statsDisplay.style.cssText = `
            position: absolute;
            top: 10px;
            left: 10px;
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 10px;
            border-radius: 4px;
            font-size: 12px;
            font-family: monospace;
            z-index: 100;
        `;
        
        this.canvas.parentElement.appendChild(this.statsDisplay);
        this.updateStatsDisplay();
    }
    
    updateStatsDisplay() {
        if (!this.statsDisplay) return;
        
        const info = this.renderer.info;
        this.statsDisplay.innerHTML = `
            <div>FPS: ${this.performanceMonitor.fps}</div>
            <div>Triangles: ${info.render.triangles}</div>
            <div>Draw Calls: ${info.render.calls}</div>
            <div>Geometries: ${info.memory.geometries}</div>
            <div>Textures: ${info.memory.textures}</div>
        `;
    }
    
    hideStatsDisplay() {
        if (this.statsDisplay) {
            this.statsDisplay.remove();
            this.statsDisplay = null;
        }
    }
    
    showToast(message, type = 'info') {
        // Create toast notification
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: rgba(0, 0, 0, 0.9);
            color: white;
            padding: 12px 16px;
            border-radius: 6px;
            font-size: 13px;
            z-index: 10000;
            border-left: 4px solid ${type === 'success' ? '#00ff88' : type === 'error' ? '#ff4444' : type === 'warning' ? '#ffaa00' : '#00d4ff'};
            transform: translateX(100%);
            transition: transform 0.3s ease;
        `;
        
        toast.textContent = message;
        document.body.appendChild(toast);
        
        // Show toast
        setTimeout(() => toast.style.transform = 'translateX(0)', 10);
        
        // Hide and remove toast
        setTimeout(() => {
            toast.style.transform = 'translateX(100%)';
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.remove();
                }
            }, 300);
        }, 3000);
    }
    
    getCsrfToken() {
        const metaTag = document.querySelector('meta[name="csrf-token"]');
        return metaTag ? metaTag.getAttribute('content') : null;
    }
    
    dispose() {
        // Clean up resources
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
        }
        
        if (this.boneMesh) {
            this.scene.remove(this.boneMesh);
            this.boneMesh.geometry.dispose();
            this.boneMesh.material.dispose();
        }
        
        if (this.volumeTexture) {
            this.volumeTexture.dispose();
        }
        
        if (this.renderer) {
            this.renderer.dispose();
        }
        
        if (this.controls) {
            this.controls.dispose();
        }
        
        // Remove event listeners
        window.removeEventListener('resize', this.onWindowResize.bind(this));
        
        console.log('🧹 3D reconstruction resources disposed');
    }
}

// Global instance for integration with DICOM viewer
window.MasterpieceBoneReconstruction3D = MasterpieceBoneReconstruction3D;