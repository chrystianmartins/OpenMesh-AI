use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use base64::Engine;
use clap::{Parser, Subcommand};
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use rand::rngs::OsRng;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use tracing::{error, info, warn};

#[derive(Debug, Parser)]
#[command(name = "openmesh-worker", version, about = "OpenMesh-AI worker CLI")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Debug, Subcommand)]
enum Commands {
    Init {
        #[arg(long)]
        coordinator_url: String,
        #[arg(long)]
        api_key: String,
        #[arg(long)]
        name: String,
        #[arg(long)]
        region: String,
    },
    Keys,
    Bench,
    Start,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Config {
    coordinator_url: String,
    api_key: String,
    name: String,
    region: String,
    public_key: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct BenchSpec {
    cpu: String,
    ram: String,
    os: String,
    gpu: Option<String>,
}

fn main() -> Result<(), String> {
    init_tracing();
    let cli = Cli::parse();

    match cli.command {
        Commands::Init {
            coordinator_url,
            api_key,
            name,
            region,
        } => cmd_init(Config {
            coordinator_url,
            api_key,
            name,
            region,
            public_key: None,
        }),
        Commands::Keys => cmd_keys(),
        Commands::Bench => cmd_bench(),
        Commands::Start => cmd_start(),
    }
}

fn init_tracing() {
    let _ = tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .try_init();
}

fn openmesh_dir() -> Result<PathBuf, String> {
    let home = std::env::var("HOME").map_err(|_| "HOME env var not found".to_string())?;
    let dir = PathBuf::from(home).join(".openmesh");
    fs::create_dir_all(&dir).map_err(|e| format!("create ~/.openmesh failed: {e}"))?;
    Ok(dir)
}

fn config_path() -> Result<PathBuf, String> {
    Ok(openmesh_dir()?.join("config.toml"))
}

fn key_path() -> Result<PathBuf, String> {
    Ok(openmesh_dir()?.join("private_key"))
}

fn specs_path() -> Result<PathBuf, String> {
    Ok(openmesh_dir()?.join("specs.json"))
}

fn cmd_init(config: Config) -> Result<(), String> {
    let path = config_path()?;
    let toml = toml::to_string_pretty(&config).map_err(|e| format!("serialize config failed: {e}"))?;
    fs::write(&path, toml).map_err(|e| format!("write config failed: {e}"))?;
    info!(path = %path.display(), "config saved");
    Ok(())
}

fn cmd_keys() -> Result<(), String> {
    let mut rng = OsRng;
    let signing_key = SigningKey::generate(&mut rng);
    let verifying_key = signing_key.verifying_key();

    let private_b64 = base64::engine::general_purpose::STANDARD.encode(signing_key.to_bytes());
    let public_b64 = base64::engine::general_purpose::STANDARD.encode(verifying_key.to_bytes());

    let path = key_path()?;
    write_private_key_secure(&path, &private_b64)?;

    let mut cfg = read_config_optional()?.ok_or_else(|| "run init before keys".to_string())?;
    cfg.public_key = Some(public_b64.clone());
    let cfg_path = config_path()?;
    let toml = toml::to_string_pretty(&cfg).map_err(|e| format!("serialize config failed: {e}"))?;
    fs::write(cfg_path, toml).map_err(|e| format!("update config failed: {e}"))?;

    println!("public_key={public_b64}");
    Ok(())
}

#[cfg(unix)]
fn write_private_key_secure(path: &Path, content: &str) -> Result<(), String> {
    use std::os::unix::fs::OpenOptionsExt;

    let mut file = fs::OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .mode(0o600)
        .open(path)
        .map_err(|e| format!("open private_key failed: {e}"))?;
    file.write_all(content.as_bytes())
        .map_err(|e| format!("write private_key failed: {e}"))?;
    Ok(())
}

#[cfg(not(unix))]
fn write_private_key_secure(path: &Path, content: &str) -> Result<(), String> {
    fs::write(path, content).map_err(|e| format!("write private_key failed: {e}"))
}

fn cmd_bench() -> Result<(), String> {
    let specs = BenchSpec {
        cpu: std::env::consts::ARCH.to_string(),
        ram: detect_ram(),
        os: std::env::consts::OS.to_string(),
        gpu: detect_gpu(),
    };

    let value = serde_json::to_value(specs).map_err(|e| format!("serialize bench failed: {e}"))?;
    let canonical = canonical_json_string(&value)?;
    let path = specs_path()?;
    fs::write(&path, canonical).map_err(|e| format!("write specs failed: {e}"))?;
    info!(path = %path.display(), "bench specs saved");
    Ok(())
}

fn detect_ram() -> String {
    #[cfg(target_os = "linux")]
    {
        if let Ok(meminfo) = fs::read_to_string("/proc/meminfo") {
            if let Some(line) = meminfo.lines().find(|l| l.starts_with("MemTotal:")) {
                return line.replace("MemTotal:", "").trim().to_string();
            }
        }
    }
    "unknown".to_string()
}

fn detect_gpu() -> Option<String> {
    #[cfg(target_os = "linux")]
    {
        if let Ok(data) = fs::read_to_string("/proc/driver/nvidia/gpus/0/information") {
            if let Some(model_line) = data.lines().find(|l| l.starts_with("Model:")) {
                return Some(model_line.replace("Model:", "").trim().to_string());
            }
        }
    }
    None
}

fn cmd_start() -> Result<(), String> {
    let cfg = read_config_optional()?.ok_or_else(|| "config not found, run init".to_string())?;
    let signing_key = load_private_key()?;

    let mut backoff = Duration::from_secs(1);
    loop {
        match run_cycle(&cfg, &signing_key) {
            Ok(()) => backoff = Duration::from_secs(1),
            Err(e) => {
                error!(error = %e, "cycle failed");
                warn!(sleep_s = backoff.as_secs(), "applying exponential backoff");
                thread::sleep(backoff);
                backoff = std::cmp::min(backoff * 2, Duration::from_secs(30));
            }
        }
    }
}

fn run_cycle(cfg: &Config, signing_key: &SigningKey) -> Result<(), String> {
    heartbeat(cfg)?;
    let job = poll_job(cfg)?;
    let result = execute_dummy(&job)?;
    submit_signed_result(cfg, signing_key, &result)?;
    Ok(())
}

fn heartbeat(cfg: &Config) -> Result<(), String> {
    if cfg.coordinator_url.trim().is_empty() {
        return Err("invalid coordinator_url".to_string());
    }
    info!(worker = %cfg.name, region = %cfg.region, "heartbeat sent");
    Ok(())
}

fn poll_job(cfg: &Config) -> Result<Value, String> {
    if cfg.api_key.trim().is_empty() {
        return Err("api_key is empty".to_string());
    }
    let job = serde_json::json!({
        "job_id": "dummy-001",
        "payload": {"action": "noop"}
    });
    info!("job polled");
    Ok(job)
}

fn execute_dummy(job: &Value) -> Result<Value, String> {
    let job_id = job
        .get("job_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "job_id missing".to_string())?;
    let result = serde_json::json!({
        "job_id": job_id,
        "status": "ok",
        "output": "dummy execution"
    });
    info!(job_id, "job executed (dummy)");
    Ok(result)
}

fn submit_signed_result(cfg: &Config, signing_key: &SigningKey, result: &Value) -> Result<(), String> {
    let canonical = canonical_json_string(result)?;
    let digest = sha256_hex(canonical.as_bytes());
    let signature = signing_key.sign(digest.as_bytes());
    let signature_b64 = base64::engine::general_purpose::STANDARD.encode(signature.to_bytes());

    info!(
        worker = %cfg.name,
        digest = %digest,
        signature = %signature_b64,
        "signed result submitted"
    );
    Ok(())
}

fn read_config_optional() -> Result<Option<Config>, String> {
    let path = config_path()?;
    if !path.exists() {
        return Ok(None);
    }
    let raw = fs::read_to_string(path).map_err(|e| format!("read config failed: {e}"))?;
    let cfg: Config = toml::from_str(&raw).map_err(|e| format!("parse config failed: {e}"))?;
    Ok(Some(cfg))
}

fn load_private_key() -> Result<SigningKey, String> {
    let raw = fs::read_to_string(key_path()?).map_err(|e| format!("read private_key failed: {e}"))?;
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(raw.trim())
        .map_err(|e| format!("decode private_key failed: {e}"))?;
    let arr: [u8; 32] = bytes
        .as_slice()
        .try_into()
        .map_err(|_| "private key must be 32 bytes".to_string())?;
    Ok(SigningKey::from_bytes(&arr))
}

fn canonical_json_string(value: &Value) -> Result<String, String> {
    let canonical = canonicalize_value(value);
    serde_json::to_string(&canonical).map_err(|e| format!("canonical json serialization failed: {e}"))
}

fn canonicalize_value(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut sorted = BTreeMap::new();
            for (k, v) in map {
                sorted.insert(k.clone(), canonicalize_value(v));
            }
            let mut out = Map::new();
            for (k, v) in sorted {
                out.insert(k, v);
            }
            Value::Object(out)
        }
        Value::Array(arr) => Value::Array(arr.iter().map(canonicalize_value).collect()),
        _ => value.clone(),
    }
}

fn sha256_hex(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    let digest = hasher.finalize();
    hex_bytes(&digest)
}

fn hex_bytes(data: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(data.len() * 2);
    for &byte in data {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

#[allow(dead_code)]
fn verify_signature(verifying_key: &VerifyingKey, message: &[u8], sig_b64: &str) -> Result<bool, String> {
    let sig_bytes = base64::engine::general_purpose::STANDARD
        .decode(sig_b64)
        .map_err(|e| format!("decode signature failed: {e}"))?;
    let sig_arr: [u8; 64] = sig_bytes
        .as_slice()
        .try_into()
        .map_err(|_| "signature must be 64 bytes".to_string())?;
    let signature = Signature::from_bytes(&sig_arr);
    Ok(verifying_key.verify(message, &signature).is_ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_json_is_deterministic() {
        let a = serde_json::json!({"b": 1, "a": {"d": 4, "c": 3}});
        let b = serde_json::json!({"a": {"c": 3, "d": 4}, "b": 1});

        let ca = canonical_json_string(&a).expect("must canonicalize");
        let cb = canonical_json_string(&b).expect("must canonicalize");
        assert_eq!(ca, cb);
        assert_eq!(ca, r#"{"a":{"c":3,"d":4},"b":1}"#);
    }

    #[test]
    fn sha256_matches_known_vector() {
        let digest = sha256_hex(b"abc");
        assert_eq!(
            digest,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn signature_and_local_verification_work() {
        let mut rng = OsRng;
        let sk = SigningKey::generate(&mut rng);
        let vk = sk.verifying_key();

        let msg = b"openmesh";
        let sig = sk.sign(msg);
        let sig_b64 = base64::engine::general_purpose::STANDARD.encode(sig.to_bytes());

        let verified = verify_signature(&vk, msg, &sig_b64).expect("verification should run");
        assert!(verified);
    }
}
