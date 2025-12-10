use std::env;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::{Context, Result};
use dicom_object::DicomObject;
use dicom_ul::association::server::{Server, ServerDriver};
use dicom_ul::association::service::ServiceClassProvider;
use dicom_ul::presentation::PresentationContextResult;
use dicom_ul::pdu::{PDataValue, PDataValueType};
use dicom_ul::{ServiceClassProviderExt, Uid};
use reqwest::Client;
use serde::Serialize;
use tokio::fs;
use tokio::sync::Mutex;
use tracing::{error, info};

#[derive(Clone, Serialize)]
struct IngestPayload {
    file_path: PathBuf,
    calling_aet: String,
    remote_host: String,
}

struct FastApiForwarder {
    client: Client,
    endpoint: String,
}

impl FastApiForwarder {
    async fn send(&self, payload: &IngestPayload) -> Result<()> {
        self.client
            .post(&self.endpoint)
            .json(payload)
            .send()
            .await
            .context("Failed to send ingest payload")?
            .error_for_status()
            .context("Gateway rejected ingest payload")?;
        Ok(())
    }
}

struct NoctisReceiver {
    storage_root: PathBuf,
    forwarder: FastApiForwarder,
}

impl NoctisReceiver {
    fn new(storage_root: PathBuf, forwarder: FastApiForwarder) -> Self {
        Self {
            storage_root,
            forwarder,
        }
    }

    async fn persist_dataset(&self, pdata: &PDataValue, calling_aet: &str) -> Result<PathBuf> {
        let study_dir = self.storage_root.join(calling_aet);
        fs::create_dir_all(&study_dir).await?;
        let temp = tempfile::NamedTempFile::new_in(&study_dir)?;
        tokio::fs::write(temp.path(), &pdata.data_fragment).await?;
        Ok(temp.into_temp_path().to_path_buf())
    }
}

#[async_trait::async_trait]
impl ServiceClassProvider for NoctisReceiver {
    async fn handle_presentation_context(&self, result: PresentationContextResult) {
        info!(?result, "Presentation context negotiated");
    }

    async fn handle_p_data(&self, value: PDataValue, assoc: &mut dicom_ul::association::Association) {
        if value.pdv_type != PDataValueType::Data {
            return;
        }
        let calling_aet = assoc
            .caller_ae_title()
            .unwrap_or_else(|_| "UNKNOWN".into())
            .trim()
            .to_string();
        let remote_host = assoc
            .peer_addr()
            .map(|addr| addr.ip().to_string())
            .unwrap_or_else(|_| "unknown".into());
        match self.persist_dataset(&value, &calling_aet).await {
            Ok(file_path) => {
                let payload = IngestPayload {
                    file_path: file_path.clone(),
                    calling_aet: calling_aet.clone(),
                    remote_host,
                };
                if let Err(err) = self.forwarder.send(&payload).await {
                    error!(?err, "Failed to forward ingest payload");
                }
            }
            Err(err) => error!(?err, "Failed to persist dataset"),
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    let port: u16 = env::var("NOCTIS_DICOM_PORT")
        .unwrap_or_else(|_| "11112".into())
        .parse()
        .context("Invalid NOCTIS_DICOM_PORT")?;
    let aet = env::var("NOCTIS_DICOM_AET").unwrap_or_else(|_| "NOCTIS_SCP".into());
    let api_url = env::var("NOCTIS_FASTAPI_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:9000/dicom/ingest".into());
    let storage_root = PathBuf::from(
        env::var("NOCTIS_DICOM_STORAGE").unwrap_or_else(|_| "./media/dicom/received".into()),
    );
    fs::create_dir_all(&storage_root).await?;

    let forwarder = FastApiForwarder {
        client: Client::new(),
        endpoint: api_url,
    };
    let provider = NoctisReceiver::new(storage_root, forwarder);

    info!(%aet, %port, "Starting Rust DICOM receiver");
    let mut server = Server::new(aet.into_bytes(), ([0, 0, 0, 0], port).into());
    server
        .run(provider)
        .await
        .context("Receiver terminated unexpectedly")?;

    Ok(())
}
