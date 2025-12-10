use std::borrow::Cow;
use std::path::Path;

use dicom_object::open_file;
use pyo3::prelude::*;
use serde::Serialize;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CoreError {
    #[error("Failed to open DICOM file: {0}")]
    Open(#[from] dicom_object::Error),
    #[error("Pixel data missing from DICOM file")]
    MissingPixelData,
}

#[derive(Debug, Serialize)]
pub struct Metadata {
    patient_id: Option<String>,
    patient_name: Option<String>,
    study_instance_uid: Option<String>,
    series_instance_uid: Option<String>,
    sop_instance_uid: Option<String>,
    modality: Option<String>,
}

fn to_string(element: Option<Cow<'_, str>>) -> Option<String> {
    element.map(|cow| cow.trim().to_string()).filter(|s| !s.is_empty())
}

fn extract_metadata_internal(path: &Path) -> Result<Metadata, CoreError> {
    let obj = open_file(path)?;
    let patient_id = obj.element_by_name("PatientID").ok().and_then(|el| el.to_str().ok());
    let patient_name = obj.element_by_name("PatientName").ok().and_then(|el| el.to_str().ok());
    let study_uid = obj
        .element_by_name("StudyInstanceUID")
        .ok()
        .and_then(|el| el.to_str().ok());
    let series_uid = obj
        .element_by_name("SeriesInstanceUID")
        .ok()
        .and_then(|el| el.to_str().ok());
    let sop_uid = obj
        .element_by_name("SOPInstanceUID")
        .ok()
        .and_then(|el| el.to_str().ok());
    let modality = obj.element_by_name("Modality").ok().and_then(|el| el.to_str().ok());

    Ok(Metadata {
        patient_id: to_string(patient_id),
        patient_name: to_string(patient_name),
        study_instance_uid: to_string(study_uid),
        series_instance_uid: to_string(series_uid),
        sop_instance_uid: to_string(sop_uid),
        modality: to_string(modality),
    })
}

#[pyfunction]
fn extract_metadata(path: &str) -> PyResult<String> {
    let metadata = extract_metadata_internal(Path::new(path))
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(err.to_string()))?;
    Ok(serde_json::to_string(&metadata).unwrap_or_else(|_| "{}".to_string()))
}

#[pyfunction]
fn window_level(pixels: Vec<f32>, window_width: f32, window_center: f32) -> PyResult<Vec<u8>> {
    if pixels.is_empty() {
        return Ok(vec![]);
    }
    let ww = window_width.max(1.0);
    let wc = window_center;
    let lower = wc - ww / 2.0;
    let upper = wc + ww / 2.0;
    let scaled: Vec<u8> = pixels
        .into_iter()
        .map(|value| {
            let clamped = if value < lower {
                lower
            } else if value > upper {
                upper
            } else {
                value
            };
            let normalized = (clamped - lower) / (upper - lower);
            (normalized * 255.0).clamp(0.0, 255.0) as u8
        })
        .collect();
    Ok(scaled)
}

#[pymodule]
fn noctis_dicom_core(_py: Python<'_>, module: &PyModule) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(extract_metadata, module)?)?;
    module.add_function(wrap_pyfunction!(window_level, module)?)?;
    Ok(())
}
