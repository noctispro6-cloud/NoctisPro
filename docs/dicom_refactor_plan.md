# DICOM Receiver + Viewer Modernization Plan

> Objective: migrate the heavy DICOM ingestion pipeline to a Rust-based service that exposes its control/ingress APIs via FastAPI while porting the in-browser viewer pipeline to WebAssembly, all without changing the current UI theme or dashboard semantics for noctis-pro.com.

## 1. Current Baseline

- **Receiver**: `dicom_receiver.py` (Python, pynetdicom) performs C-STORE/C-ECHO handling and writes fully processed objects into the Django database/media tree.
- **Viewer**: `dicom_viewer` Django app renders HTML templates (`viewer.html`, `masterpiece_viewer.html`, etc.) with large JS bundles (e.g., `static/js/dicom-viewer-enhanced.js`) that execute all rendering in plain JavaScript.
- **Domain handling**: Django `ALLOWED_HOSTS`, CORS and CSRF trusts still mention historical DuckDNS hosts; noctis-pro.com must become the canonical deployment domain.

## 2. Target Architecture Overview

1. **Rust DICOM Receiver (noctis-dicom-rx)**
   - Implemented with the [`dicom-ul`](https://github.com/Enet4/dicom-ul) crate for DICOM networking and [`dicom-object`](https://github.com/Enet4/dicom-rs) for dataset parsing.
   - Emits structured ingest events through a lightweight message bus (Redis Streams or NATS) so downstream services can process without blocking the DIMSE association.
   - Persists raw DICOM objects to the existing storage layout (`media/dicom/received/<study>/<series>/<sop>.dcm`) to avoid breaking downstream code.
   - Builds with `cargo` into a static binary packaged under `services/dicom_receiver_rust/` and exposed via systemd unit `noctis-pro-dicom-rust.service`.

2. **FastAPI Control Plane (noctis-fastapi-gateway)**
   - Offers HTTP endpoints to start/stop the Rust receiver, inspect live stats, and receive ingest notifications via webhooks.
   - Uses [`pyo3`](https://pyo3.rs) bindings to call a minimal Rust library (`noctis_dicom_core`) for CPU-intensive operations (HU calibration, thumbnail prep) while FastAPI takes care of auth and response serialization.
   - Emits Django-compatible webhooks (`POST /api/dicom/ingest`) so the existing Django app can register and update models without tight coupling.

3. **WebAssembly Viewer Core (noctis-viewer-wasm)**
   - Re-implements the hot path rendering features (window/level transforms, MPR slicing, annotations) using Rust + `wasm-bindgen` compiled to a `.wasm` module that can be loaded by the existing viewer HTML templates without changing layout/theme.
   - JavaScript glue (tiny TypeScript module) exposes stable functions like `renderSlice`, `applyWindowLevel`, `exportAnnotation`. The template keeps the same CSS/DOM structure, satisfying the "dashboard theme stays the same" constraint.
   - The WASM bundle lives under `static/wasm/` and is lazy-loaded via `WebAssembly.instantiateStreaming` so legacy users can gracefully fall back to the current JS implementation while the migration is staged.

## 3. Incremental Delivery Plan

| Phase | Scope | Key Tasks |
| --- | --- | --- |
| 0 | Prep | add noctis-pro.com to Django ALLOWED_HOSTS/CORS/CSRF (done); create shared proto/schema for ingest events. |
| 1 | Rust Core Library | scaffold `rust/noctis_dicom_core` crate with dataset parsing, metadata extraction, thumbnail generation; expose via `pyo3` + `maturin`. |
| 2 | FastAPI Wrapper | new service `services/dicom_fastapi/main.py` that imports `noctis_dicom_core`, exposes `/ingest`, `/stats`, `/health`, and forwards persisted files to Django asynchronously. |
| 3 | Rust DIMSE Receiver | add binary crate `rust/noctis_dicom_receiver` that uses `dicom-ul` to accept C-STORE requests and streams them into the FastAPI pipeline (Unix socket ➜ HTTP). |
| 4 | WASM Viewer MVP | port existing `dicom_viewer/dicom_utils.py` algorithms to Rust, compile to `static/wasm/noctis_viewer_bg.wasm`, and update JS glue to delegate heavy computations. Preserve CSS/HTML to keep dashboard appearance identical. |
| 5 | Cut-over & Observability | integrate Prometheus exporters, update systemd units, document rollback steps, and add smoke tests (pytest + Playwright) to cover both Python and WASM code paths. |

## 4. Risk & Mitigation Checklist

- **DIMSE feature parity**: ensure the Rust receiver matches pynetdicom behavior for AE Title validation and transfer syntaxes; add integration tests using Orthanc's storescu.
- **FastAPI auth**: re-use Django session tokens by issuing service-to-service API keys stored in `NOCTIS_FASTAPI_TOKEN` env var; validate before accepting ingest POSTs.
- **Browser compatibility**: maintain JS fallback for browsers without WASM SIMD by feature-detecting `WebAssembly.validate` and toggling modules accordingly; no CSS/theme changes required.
- **Operational rollout**: run Rust + FastAPI services in parallel with the Python receiver until log parity is achieved; use canary facility AE Titles.

## 5. Next Steps

1. Create repo structure under `rust/` with `Cargo.toml` workspace referencing `noctis_dicom_core` (lib), `noctis_dicom_receiver` (bin), and `noctis_viewer_wasm` (cdylib for wasm32).
2. Scaffold FastAPI app under `services/dicom_fastapi/` with uvicorn entrypoint and initial `/healthz` route.
3. Extract existing Python metadata logic (`DicomImageProcessor.extract_enhanced_metadata`) into rust crate to guarantee functional parity before enabling DIMSE ingestion.
4. Prototype WASM window/level function and integrate into `static/js/dicom-viewer-enhanced.js` via dynamic import while leaving the DOM/theme untouched.

Keeping the dashboard aesthetics unchanged remains a hard requirement throughout the migration; all UI updates must respect the existing CSS variables and layout in `templates/dicom_viewer/masterpiece_viewer.html` and related styles.
