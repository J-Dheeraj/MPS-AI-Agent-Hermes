#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

const MAX_PROPOSAL_BYTES: u64 = 1_048_576;

#[derive(Debug, Serialize, Deserialize, Clone)]
struct ProposalSummary {
    id: String,
    agency: String,
    issue: String,
    file_name: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct ProposalDetail {
    raw: serde_json::Value,
    file_name: String,
    sha256: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct Decision {
    schema_version: u8,
    decision: String,
    reviewer_id: String,
    reviewer_note: Option<String>,
    proposal_sha256: String,
    decided_at_unix: u64,
}

fn canonical_root(base: &str) -> Result<PathBuf, String> {
    let root = fs::canonicalize(base).map_err(|e| format!("Invalid review root: {e}"))?;
    if !root.is_dir() {
        return Err("Review root must be a directory".to_string());
    }
    let pending = root.join("pending");
    if !pending.is_dir() {
        return Err("Review root must contain a pending directory".to_string());
    }
    Ok(root)
}

fn safe_file_name(file_name: &str) -> Result<&str, String> {
    let path = Path::new(file_name);
    let mut components = path.components();
    let only = components.next();
    if components.next().is_some()
        || !matches!(only, Some(Component::Normal(_)))
        || path.file_name().and_then(|name| name.to_str()) != Some(file_name)
        || path.extension().and_then(|ext| ext.to_str()) != Some("json")
        || file_name.ends_with(".decision.json")
    {
        return Err("Invalid proposal file name".to_string());
    }
    Ok(file_name)
}

fn proposal_path(root: &Path, file_name: &str) -> Result<PathBuf, String> {
    safe_file_name(file_name)?;
    let pending = fs::canonicalize(root.join("pending"))
        .map_err(|e| format!("Invalid pending directory: {e}"))?;
    let candidate = fs::canonicalize(pending.join(file_name))
        .map_err(|e| format!("Proposal not found: {e}"))?;
    if !candidate.starts_with(&pending) || !candidate.is_file() {
        return Err("Proposal path is outside pending".to_string());
    }
    Ok(candidate)
}

fn read_proposal_bytes(path: &Path) -> Result<Vec<u8>, String> {
    let metadata = fs::metadata(path).map_err(|e| format!("Could not inspect proposal: {e}"))?;
    if metadata.len() > MAX_PROPOSAL_BYTES {
        return Err("Proposal exceeds the 1 MiB size limit".to_string());
    }
    fs::read(path).map_err(|e| format!("Could not read proposal: {e}"))
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn target_dir(root: &Path, decision: &str) -> Result<PathBuf, String> {
    let name = match decision {
        "approve" => "approved",
        "reject" => "rejected",
        _ => return Err("Decision must be approve or reject".to_string()),
    };
    let directory = root.join(name);
    fs::create_dir_all(&directory)
        .map_err(|e| format!("Could not create {}: {e}", directory.display()))?;
    Ok(directory)
}

#[tauri::command]
fn list_pending(base_dir: String) -> Result<Vec<ProposalSummary>, String> {
    let root = canonical_root(&base_dir)?;
    let pending = root.join("pending");
    let entries = fs::read_dir(&pending)
        .map_err(|e| format!("Could not read {}: {e}", pending.display()))?;

    let mut out = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        let Some(file_name) = path.file_name().and_then(|name| name.to_str()) else {
            continue;
        };
        if safe_file_name(file_name).is_err() {
            continue;
        }
        let Ok(bytes) = read_proposal_bytes(&path) else {
            continue;
        };
        let Ok(value) = serde_json::from_slice::<serde_json::Value>(&bytes) else {
            continue;
        };
        let id = value
            .get("id")
            .and_then(|item| item.as_str())
            .unwrap_or(file_name)
            .to_string();
        let agency = value
            .get("agency")
            .and_then(|item| item.as_str())
            .unwrap_or("?")
            .to_string();
        let issue = value
            .get("issue")
            .and_then(|item| item.as_str())
            .unwrap_or("(no issue summary)")
            .to_string();
        out.push(ProposalSummary {
            id,
            agency,
            issue,
            file_name: file_name.to_string(),
        });
    }
    out.sort_by(|left, right| left.file_name.cmp(&right.file_name));
    Ok(out)
}

#[tauri::command]
fn read_proposal(base_dir: String, file_name: String) -> Result<ProposalDetail, String> {
    let root = canonical_root(&base_dir)?;
    let path = proposal_path(&root, &file_name)?;
    let bytes = read_proposal_bytes(&path)?;
    let raw = serde_json::from_slice::<serde_json::Value>(&bytes)
        .map_err(|e| format!("Malformed proposal JSON: {e}"))?;
    Ok(ProposalDetail {
        raw,
        file_name,
        sha256: sha256_hex(&bytes),
    })
}

#[tauri::command]
fn decide_proposal(
    base_dir: String,
    file_name: String,
    decision: String,
    reviewer_id: String,
    reviewer_note: Option<String>,
) -> Result<(), String> {
    let reviewer = reviewer_id.trim();
    if reviewer.len() < 3 || reviewer.len() > 100 {
        return Err("Reviewer ID must be between 3 and 100 characters".to_string());
    }
    if reviewer_note.as_ref().is_some_and(|note| note.len() > 2_000) {
        return Err("Reviewer note must not exceed 2000 characters".to_string());
    }

    let root = canonical_root(&base_dir)?;
    let source = proposal_path(&root, &file_name)?;
    let proposal_bytes = read_proposal_bytes(&source)?;
    serde_json::from_slice::<serde_json::Value>(&proposal_bytes)
        .map_err(|e| format!("Malformed proposal JSON: {e}"))?;

    let destination_dir = target_dir(&root, &decision)?;
    let destination = destination_dir.join(safe_file_name(&file_name)?);
    let sidecar_name = format!("{file_name}.decision.json");
    let sidecar_destination = destination_dir.join(&sidecar_name);
    if destination.exists() || sidecar_destination.exists() {
        return Err("A decision for this proposal already exists".to_string());
    }

    let decision_record = Decision {
        schema_version: 1,
        decision: if decision == "approve" {
            "approved".to_string()
        } else {
            "rejected".to_string()
        },
        reviewer_id: reviewer.to_string(),
        reviewer_note,
        proposal_sha256: sha256_hex(&proposal_bytes),
        decided_at_unix: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|e| e.to_string())?
            .as_secs(),
    };
    let body = serde_json::to_vec_pretty(&decision_record).map_err(|e| e.to_string())?;

    let temporary_sidecar = root
        .join("pending")
        .join(format!(".{file_name}.decision.tmp"));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary_sidecar)
        .map_err(|e| format!("Could not create decision record: {e}"))?;
    file.write_all(&body)
        .and_then(|_| file.sync_all())
        .map_err(|e| format!("Could not persist decision record: {e}"))?;

    if let Err(error) = fs::rename(&source, &destination) {
        let _ = fs::remove_file(&temporary_sidecar);
        return Err(format!("Could not move proposal: {error}"));
    }
    if let Err(error) = fs::rename(&temporary_sidecar, &sidecar_destination) {
        let _ = fs::rename(&destination, &source);
        let _ = fs::remove_file(&temporary_sidecar);
        return Err(format!("Could not finalise decision record: {error}"));
    }
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            list_pending,
            read_proposal,
            decide_proposal
        ])
        .setup(|app| {
            #[cfg(debug_assertions)]
            {
                use tauri::Manager;
                if let Some(window) = app.get_webview_window("main") {
                    window.open_devtools();
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Hermes Review");
}

#[cfg(test)]
mod tests {
    use super::safe_file_name;

    #[test]
    fn accepts_single_json_file_name() {
        assert!(safe_file_name("hdb-proposal.json").is_ok());
    }

    #[test]
    fn rejects_path_traversal_and_sidecars() {
        assert!(safe_file_name("../outside.json").is_err());
        assert!(safe_file_name("folder/inside.json").is_err());
        assert!(safe_file_name("proposal.json.decision.json").is_err());
        assert!(safe_file_name("proposal.md").is_err());
    }
}
