// Hermes skill-review companion app.
//
// Purpose: give an admin/vetter a lightweight desktop tool to review the
// weekly batch of GEPA-proposed skill/prompt corrections *before* they're
// folded into nanoClaw's letter-drafting prompts -- the human-review gate
// the proposal calls for in section 13 ("Keep human review before final use").
//
// Expected on-disk layout (a folder the reviewer picks via the native dialog):
//
//   gepa-proposals/
//     pending/    *.json   <- proposals waiting for a decision
//     approved/   *.json   <- moved here on approve, plus a .decision.json sidecar
//     rejected/   *.json   <- moved here on reject,  plus a .decision.json sidecar
//
// Each proposal JSON is expected to look roughly like:
//   {
//     "id": "2026-06-01-hdb-tone",
//     "agency": "HDB",
//     "issue": "Letter too casual",
//     "correction": "Use formal agency-facing tone",
//     "before": "...sample draft excerpt...",
//     "after": "...corrected excerpt..."
//   }
//
// All file I/O happens through tauri-plugin-fs / tauri-plugin-dialog, scoped
// to whatever directory the reviewer explicitly opens -- nothing is read or
// written outside that chosen folder.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

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
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct Decision {
    decision: String, // "approved" | "rejected"
    reviewer_note: Option<String>,
    decided_at: String,
}

fn pending_dir(base: &str) -> PathBuf {
    Path::new(base).join("pending")
}

fn target_dir(base: &str, decision: &str) -> Result<PathBuf, String> {
    match decision {
        "approve" => Ok(Path::new(base).join("approved")),
        "reject" => Ok(Path::new(base).join("rejected")),
        other => Err(format!("Unknown decision '{other}' -- expected 'approve' or 'reject'")),
    }
}

/// List pending proposals in `<base>/pending/*.json`. Malformed files are
/// skipped (logged to stderr) rather than failing the whole listing -- one
/// bad GEPA export shouldn't block reviewing the rest of the batch.
#[tauri::command]
fn list_pending(base_dir: String) -> Result<Vec<ProposalSummary>, String> {
    let dir = pending_dir(&base_dir);
    if !dir.exists() {
        return Ok(vec![]);
    }
    let entries = fs::read_dir(&dir).map_err(|e| format!("Couldn't read {}: {e}", dir.display()))?;

    let mut out = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }
        let file_name = path.file_name().and_then(|n| n.to_str()).unwrap_or_default().to_string();
        match fs::read_to_string(&path).ok().and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok()) {
            Some(v) => {
                let id = v.get("id").and_then(|x| x.as_str()).unwrap_or(&file_name).to_string();
                let agency = v.get("agency").and_then(|x| x.as_str()).unwrap_or("?").to_string();
                let issue = v.get("issue").and_then(|x| x.as_str()).unwrap_or("(no issue summary)").to_string();
                out.push(ProposalSummary { id, agency, issue, file_name });
            }
            None => eprintln!("Skipping malformed proposal file: {}", path.display()),
        }
    }
    out.sort_by(|a, b| a.file_name.cmp(&b.file_name));
    Ok(out)
}

/// Read the full JSON body of one proposal so the UI can render a before/after diff.
#[tauri::command]
fn read_proposal(base_dir: String, file_name: String) -> Result<ProposalDetail, String> {
    let path = pending_dir(&base_dir).join(&file_name);
    let text = fs::read_to_string(&path).map_err(|e| format!("Couldn't read {}: {e}", path.display()))?;
    let raw: serde_json::Value = serde_json::from_str(&text).map_err(|e| format!("Malformed JSON in {}: {e}", file_name))?;
    Ok(ProposalDetail { raw, file_name })
}

/// Move a proposal out of `pending/` into `approved/` or `rejected/`, writing
/// a `<name>.decision.json` sidecar alongside it with the reviewer's note and
/// timestamp -- this is the audit trail for "who approved what, and why",
/// mirroring the append-only review trail philosophy of mps_server.
#[tauri::command]
fn decide_proposal(base_dir: String, file_name: String, decision: String, reviewer_note: Option<String>) -> Result<(), String> {
    let from = pending_dir(&base_dir).join(&file_name);
    let to_dir = target_dir(&base_dir, &decision)?;
    fs::create_dir_all(&to_dir).map_err(|e| format!("Couldn't create {}: {e}", to_dir.display()))?;
    let to = to_dir.join(&file_name);

    fs::rename(&from, &to).map_err(|e| format!("Couldn't move {} -> {}: {e}", from.display(), to.display()))?;

    let decision_label = if decision == "approve" { "approved" } else { "rejected" };
    let sidecar = Decision {
        decision: decision_label.to_string(),
        reviewer_note,
        decided_at: chrono_now(),
    };
    let sidecar_path = to_dir.join(format!("{file_name}.decision.json"));
    let body = serde_json::to_string_pretty(&sidecar).map_err(|e| e.to_string())?;
    fs::write(&sidecar_path, body).map_err(|e| format!("Couldn't write {}: {e}", sidecar_path.display()))?;

    Ok(())
}

/// Minimal RFC3339-ish timestamp without pulling in a chrono dependency --
/// good enough for an audit sidecar; Claude Code can swap in `chrono` if a
/// stricter format is required downstream.
fn chrono_now() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    format!("unix:{secs}")
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
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
