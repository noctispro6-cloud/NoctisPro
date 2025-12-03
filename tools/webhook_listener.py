#!/usr/bin/env python3
import hmac
import hashlib
import json
import os
import subprocess
import sys
import time
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('/var/log/noctis-webhook.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

HOST = os.environ.get("WEBHOOK_HOST", "127.0.0.1")
PORT = int(os.environ.get("WEBHOOK_PORT", "9000"))
SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
BRANCH = os.environ.get("DEPLOY_BRANCH", "refs/heads/main")
APP_DIR = os.environ.get("APP_DIR", "/workspace")
ENV_FILE = os.environ.get("ENV_FILE", "/etc/noctis/noctis.env")

# Prevent multiple simultaneous deployments
deploy_lock = Lock()
last_deploy_time = 0
MIN_DEPLOY_INTERVAL = 30  # Minimum seconds between deployments

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Use our logger instead of default stderr logging
        logger.info("%s - - [%s] %s" % (
            self.address_string(),
            self.log_date_time_string(),
            format % args
        ))

    def _verify_signature(self, body: bytes) -> bool:
        if not SECRET:
            logger.warning("No webhook secret configured - accepting all requests (INSECURE)")
            return True
        
        sig = self.headers.get("X-Hub-Signature-256", "")
        if not sig.startswith("sha256="):
            logger.warning("Missing or invalid signature header")
            return False
        
        digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        expected_sig = f"sha256={digest}"
        
        if not hmac.compare_digest(sig, expected_sig):
            logger.warning("Signature verification failed")
            return False
        
        return True

    def _can_deploy(self) -> bool:
        global last_deploy_time
        current_time = time.time()
        
        if current_time - last_deploy_time < MIN_DEPLOY_INTERVAL:
            logger.info(f"Deploy rate limited. Last deploy was {current_time - last_deploy_time:.1f}s ago")
            return False
        
        return True

    def _trigger_deployment(self) -> bool:
        global last_deploy_time
        
        if not deploy_lock.acquire(blocking=False):
            logger.warning("Deploy already in progress, skipping")
            return False
        
        try:
            if not self._can_deploy():
                return False
            
            last_deploy_time = time.time()
            logger.info(f"Triggering deployment for branch {BRANCH.split('/', 2)[-1]}")
            
            # Prepare deployment command
            deploy_cmd = [
                "/usr/bin/bash", "-lc",
                f'DEPLOY_BRANCH="{BRANCH.split("/", 2)[-1]}" ENV_FILE="{ENV_FILE}" bash "{APP_DIR}/ops/deploy_from_git.sh"'
            ]
            
            # Start deployment process
            process = subprocess.Popen(
                deploy_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True
            )
            
            # Log deployment start
            with open('/var/log/noctis-deploy.log', 'a') as f:
                f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] === WEBHOOK DEPLOYMENT STARTED ===\n")
                f.flush()
            
            # Stream output to log file in real-time
            def log_output():
                with open('/var/log/noctis-deploy.log', 'a') as f:
                    for line in process.stdout:
                        f.write(line)
                        f.flush()
                    
                    # Wait for process to complete and log result
                    return_code = process.wait()
                    f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] === DEPLOYMENT {'COMPLETED' if return_code == 0 else 'FAILED'} (exit code: {return_code}) ===\n")
                    f.flush()
                    
                    if return_code == 0:
                        logger.info("Deployment completed successfully")
                    else:
                        logger.error(f"Deployment failed with exit code {return_code}")
            
            # Start logging in background
            import threading
            threading.Thread(target=log_output, daemon=True).start()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to trigger deployment: {e}")
            return False
        finally:
            deploy_lock.release()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 10 * 1024 * 1024:  # 10MB limit
                logger.warning(f"Payload too large: {length} bytes")
                self.send_response(413)
                self.end_headers()
                self.wfile.write(b"payload too large")
                return
                
            payload = self.rfile.read(length)
            
            if not self._verify_signature(payload):
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"invalid signature")
                return
                
            try:
                event = self.headers.get("X-GitHub-Event", "")
                data = json.loads(payload.decode("utf-8"))
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON payload: {e}")
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"invalid json")
                return
                
            # Log webhook event
            repo_name = data.get("repository", {}).get("full_name", "unknown")
            ref = data.get("ref", "unknown")
            logger.info(f"Received {event} event for {repo_name} on {ref}")
            
            # Only act on push to specific branch
            if event == "push" and data.get("ref") == BRANCH:
                if self._trigger_deployment():
                    self.send_response(202)
                    self.end_headers()
                    self.wfile.write(b"deployment triggered")
                else:
                    self.send_response(429)
                    self.end_headers()
                    self.wfile.write(b"deployment rate limited or in progress")
            else:
                logger.info(f"Ignoring {event} event for {ref} (waiting for {BRANCH})")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"event ignored")
                
        except Exception as e:
            logger.error(f"Error handling webhook: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"internal server error")

    def do_GET(self):
        # Health check endpoint
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            health_info = {
                "status": "healthy",
                "webhook_host": HOST,
                "webhook_port": PORT,
                "deploy_branch": BRANCH,
                "app_dir": APP_DIR,
                "has_secret": bool(SECRET),
                "last_deploy": last_deploy_time
            }
            self.wfile.write(json.dumps(health_info).encode())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")

if __name__ == "__main__":
    try:
        # Ensure log directory exists
        os.makedirs('/var/log', exist_ok=True)
        
        # Validate configuration
        if not os.path.exists(APP_DIR):
            logger.error(f"APP_DIR does not exist: {APP_DIR}")
            sys.exit(1)
            
        if not os.path.exists(f"{APP_DIR}/ops/deploy_from_git.sh"):
            logger.error(f"Deploy script not found: {APP_DIR}/ops/deploy_from_git.sh")
            sys.exit(1)
        
        server = HTTPServer((HOST, PORT), Handler)
        logger.info(f"Webhook listener starting on {HOST}:{PORT}")
        logger.info(f"Listening for push events on branch: {BRANCH}")
        logger.info(f"App directory: {APP_DIR}")
        logger.info(f"Environment file: {ENV_FILE}")
        logger.info(f"Webhook secret configured: {'Yes' if SECRET else 'No (INSECURE)'}")
        
        server.serve_forever()
        
    except KeyboardInterrupt:
        logger.info("Webhook listener stopped by user")
    except Exception as e:
        logger.error(f"Failed to start webhook listener: {e}")
        sys.exit(1)