/* Service Worker: background DICOM uploader (worklist scope)
 *
 * Goal: keep uploads running even if the user navigates away from /worklist/upload/.
 *
 * Notes:
 * - Upload endpoint `worklist:upload_study` is `@csrf_exempt`, but requires auth cookie.
 * - We store files in IndexedDB as Blobs and upload in batches.
 */

/* global self */

const DB_NAME = 'noctis_dicom_uploads_v1';
const DB_VERSION = 1;
const STORE_SESSIONS = 'sessions';
const STORE_FILES = 'files';

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_SESSIONS)) {
        db.createObjectStore(STORE_SESSIONS, { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains(STORE_FILES)) {
        const store = db.createObjectStore(STORE_FILES, { keyPath: 'key' });
        store.createIndex('by_session', 'sessionId', { unique: false });
        store.createIndex('by_session_index', ['sessionId', 'index'], { unique: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function txDone(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error('transaction aborted'));
  });
}

async function idbGetSession(db, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_SESSIONS, 'readonly');
    const req = tx.objectStore(STORE_SESSIONS).get(id);
    req.onsuccess = () => resolve(req.result || null);
    req.onerror = () => reject(req.error);
  });
}

async function idbPutSession(db, session) {
  const tx = db.transaction(STORE_SESSIONS, 'readwrite');
  tx.objectStore(STORE_SESSIONS).put(session);
  await txDone(tx);
}

async function idbListSessions(db) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_SESSIONS, 'readonly');
    const req = tx.objectStore(STORE_SESSIONS).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

async function idbGetFileByKey(db, key) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_FILES, 'readonly');
    const req = tx.objectStore(STORE_FILES).get(key);
    req.onsuccess = () => resolve(req.result || null);
    req.onerror = () => reject(req.error);
  });
}

async function idbDeleteFile(db, key) {
  const tx = db.transaction(STORE_FILES, 'readwrite');
  tx.objectStore(STORE_FILES).delete(key);
  await txDone(tx);
}

async function idbCountFilesForSession(db, sessionId) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_FILES, 'readonly');
    const idx = tx.objectStore(STORE_FILES).index('by_session');
    const req = idx.count(sessionId);
    req.onsuccess = () => resolve(Number(req.result || 0));
    req.onerror = () => reject(req.error);
  });
}

async function broadcast(message) {
  const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  for (const c of clients) {
    try { c.postMessage(message); } catch (_) {}
  }
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function uploadSession(sessionId) {
  const db = await openDb();
  let session = await idbGetSession(db, sessionId);
  if (!session) return;

  try {
    if (session.status === 'completed') return;
    session.status = 'uploading';
    session.updatedAt = Date.now();
    session.errors = session.errors || [];
    session.uploadedFiles = session.uploadedFiles || 0;
    session.uploadedBytes = session.uploadedBytes || 0;
    session.createdStudyIds = session.createdStudyIds || [];
    session.studiesCreated = session.studiesCreated || 0;
    session.totalSeries = session.totalSeries || 0;
    await idbPutSession(db, session);

    const totalFiles = Number(session.totalFiles || 0);
    const totalBytes = Number(session.totalBytes || 0);

    // Conservative batching: avoid very large FormData requests.
    // Tunnels (ngrok/trycloudflare/loca.lt) are prone to upstream idle timeouts on long requests.
    const host = (self && self.location && self.location.hostname) ? String(self.location.hostname).toLowerCase() : '';
    const isTunnelHost = host.includes('ngrok') || host.includes('trycloudflare.com') || host.includes('loca.lt');
    const MAX_CHUNK_BYTES = isTunnelHost ? (4 * 1024 * 1024) : (16 * 1024 * 1024); // 4MB on tunnels, 16MB otherwise
    const MAX_CHUNK_FILES = isTunnelHost ? 80 : 200;

    await broadcast({ type: 'UPLOAD_STATUS', sessionId, status: 'uploading', uploadedFiles: session.uploadedFiles, totalFiles });

    while (session.nextIndex < totalFiles) {
      // Build a batch from sequential indices.
      let batchKeys = [];
      let batchBytes = 0;
      for (let i = session.nextIndex; i < totalFiles; i++) {
        const key = `${sessionId}:${i}`;
        // Stop if the file doesn't exist (e.g., already uploaded and deleted); skip forward.
        // This makes the uploader resume-safe.
        // eslint-disable-next-line no-await-in-loop
        const rec = await idbGetFileByKey(db, key);
        if (!rec) {
          session.nextIndex = i + 1;
          continue;
        }
        const sz = Number(rec.size || 0);
        if (batchKeys.length && (batchBytes + sz > MAX_CHUNK_BYTES || batchKeys.length >= MAX_CHUNK_FILES)) break;
        batchKeys.push(key);
        batchBytes += sz;
      }
      if (!batchKeys.length) break;

      // Build request.
      const formData = new FormData();
      // Server uses this to group chunks and only start processing when finalize=1.
      session.serverUploadSessionId = session.serverUploadSessionId || String(sessionId);
      session.batchIndex = Number(session.batchIndex || 0);
      const willFinish = (session.nextIndex + batchKeys.length) >= totalFiles;
      formData.append('upload_session_id', String(session.serverUploadSessionId));
      formData.append('chunk_index', String(session.batchIndex));
      // Avoid accidental finalize-by-default on the server for intermediate chunks.
      formData.append('total_chunks', '1000000000');
      if (willFinish) formData.append('finalize', '1');

      for (const key of batchKeys) {
        // eslint-disable-next-line no-await-in-loop
        const rec = await idbGetFileByKey(db, key);
        if (!rec || !rec.blob) continue;
        // IMPORTANT: avoid `new File(...)` because it's not reliably available in all SW contexts.
        // FormData.append(name, blob, filename) is widely supported and preserves the filename for Django.
        formData.append('dicom_files', rec.blob, rec.name || 'image.dcm');
      }
      // Options from the page (priority, clinical_info, facility, assign_to_me)
      if (session.options) {
        for (const [k, v] of Object.entries(session.options)) {
          if (v != null && String(v).length) formData.append(k, String(v));
        }
      }

      let ok = false;
      let lastErr = null;
      for (let attempt = 1; attempt <= 3; attempt++) {
        try {
          const resp = await fetch(session.url, {
            method: 'POST',
            body: formData,
            // Be explicit: ensure auth cookies are included.
            credentials: 'include',
            cache: 'no-store',
          });
          if (!resp.ok) {
            // Common failure modes: 302 to login, 401/403 auth, 413 payload too large
            throw new Error(`HTTP ${resp.status}`);
          }
          const data = await resp.json().catch(() => ({}));
          if (!data || data.success !== true) throw new Error((data && data.error) || 'upload failed');

          // Update stats (server-side dedup can make created_images 0; prefer images_uploaded/processed_files).
          const processed = (typeof data.images_uploaded === 'number') ? data.images_uploaded
            : (typeof data.processed_files === 'number') ? data.processed_files
            : batchKeys.length;
          session.uploadedFiles += processed;
          session.uploadedBytes += batchBytes;
          session.studiesCreated += Number(data.studies_created || 0);
          session.totalSeries += Number(data.total_series || 0);
          if (Array.isArray(data.created_study_ids)) session.createdStudyIds.push(...data.created_study_ids);
          ok = true;
          break;
        } catch (e) {
          lastErr = e;
          if (attempt < 3) await sleep(800 * Math.pow(2, attempt - 1));
        }
      }
      if (!ok) {
        const msg = (lastErr && (lastErr.message || String(lastErr))) || 'Upload failed';
        session.status = 'failed';
        session.errors.push(msg);
        session.updatedAt = Date.now();
        await idbPutSession(db, session);
        await broadcast({ type: 'UPLOAD_STATUS', sessionId, status: 'failed', error: msg });
        return;
      }

      // Delete uploaded files and advance index.
      for (const key of batchKeys) {
        // eslint-disable-next-line no-await-in-loop
        await idbDeleteFile(db, key);
      }
      session.nextIndex = Math.min(totalFiles, session.nextIndex + batchKeys.length);
      session.batchIndex = Number(session.batchIndex || 0) + 1;
      session.updatedAt = Date.now();
      await idbPutSession(db, session);

      await broadcast({
        type: 'UPLOAD_PROGRESS',
        sessionId,
        status: 'uploading',
        uploadedFiles: session.uploadedFiles,
        totalFiles,
        uploadedBytes: session.uploadedBytes,
        totalBytes,
        studiesCreated: session.studiesCreated,
        totalSeries: session.totalSeries,
      });
    }

    session.status = 'completed';
    session.updatedAt = Date.now();
    await idbPutSession(db, session);
    await broadcast({ type: 'UPLOAD_STATUS', sessionId, status: 'completed', session });
  } catch (e) {
    const msg = (e && (e.message || String(e))) || 'Upload failed';
    try {
      session.status = 'failed';
      session.errors = session.errors || [];
      session.errors.push(msg);
      session.updatedAt = Date.now();
      await idbPutSession(db, session);
    } catch (_) {}
    await broadcast({ type: 'UPLOAD_STATUS', sessionId, status: 'failed', error: msg });
  }
}

async function processPending() {
  const db = await openDb();
  const sessions = await idbListSessions(db);
  for (const s of sessions) {
    const remaining = await idbCountFilesForSession(db, s.id);
    if (remaining <= 0 && s.status !== 'completed') {
      // Nothing left to upload; mark completed.
      s.status = 'completed';
      s.updatedAt = Date.now();
      await idbPutSession(db, s);
      await broadcast({ type: 'UPLOAD_STATUS', sessionId: s.id, status: 'completed', session: s });
      continue;
    }
    // If there are remaining files, try to resume even from "failed" (e.g. after a SW update).
    if (s.status === 'pending' || s.status === 'uploading' || s.status === 'failed') {
      // eslint-disable-next-line no-await-in-loop
      await uploadSession(s.id);
    }
  }
}

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    await self.clients.claim();
    // Best-effort resume: if there are pending sessions, kick processing when SW activates.
    try { await processPending(); } catch (_) {}
  })());
});

self.addEventListener('sync', (event) => {
  if (event.tag === 'noctis-dicom-upload') {
    event.waitUntil(processPending());
  }
});

self.addEventListener('message', (event) => {
  const msg = event.data || {};
  if (msg.type === 'PING') {
    event.source?.postMessage({ type: 'PONG' });
    return;
  }
  if (msg.type === 'PROCESS_PENDING') {
    event.waitUntil(processPending());
    return;
  }
  if (msg.type === 'START_UPLOAD' && msg.sessionId) {
    event.waitUntil(uploadSession(String(msg.sessionId)));
    return;
  }
});

