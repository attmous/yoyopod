//! Admission evidence for the pinned ModemManager provider. No production defaults
//! confer qualification; live Call metadata is required separately from idle identity.
use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeSet, HashMap};
use zbus::blocking::{Connection, Proxy};

const PACKAGE_VERSION: &str = "1.24.0-1+deb13u1+yoyopod1";
const SOURCE_VERSION: &str = "1.24.0-1+deb13u1";
const RECEIPT_DIR: &str = "/var/lib/yoyopod/providers/modemmanager";
const MODEM_INTERFACE: &str = "org.freedesktop.ModemManager1.Modem";

/// Qualification recorded by the trusted compiled profile, never inferred from metadata.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Qualification {
    /// Candidate inputs exist, but framing and lifecycle evidence is not qualified.
    QualificationPending,
    /// Both reviewed evidence records bind the compiled provider inputs and modem.
    Qualified,
}

/// Exact modem identity covered by the profile and its qualification records.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModemFingerprint {
    /// Manufacturer reported by the selected modem.
    pub manufacturer: String,
    /// Reported product identity, including its hardware variant.
    pub model: String,
    /// Firmware build covered by the evidence.
    pub revision: String,
    /// Reported hardware revision covered by the evidence.
    pub hardware_revision: String,
    /// ModemManager plugin implementing the selected modem.
    pub plugin: String,
}
/// Profile format requirements; these do not substitute for a current Call dictionary.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PcmFormat {
    /// Sample encoding required by the contract.
    pub encoding: String,
    /// Sample representation and byte order.
    pub resolution: String,
    /// Required samples per second, verified separately against live metadata.
    pub rate: u32,
    /// Number of channels covered by the profile.
    pub channels: u32,
}
/// One reviewed framing or lifecycle record bound by the expected manifest.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct QualificationRecord {
    /// Evidence category: framing or lifecycle.
    pub kind: String,
    /// Canonical manifest path beneath `source/qualification/`.
    pub path: String,
    /// SHA256 of the referenced evidence bytes.
    pub sha256: String,
    /// Exact firmware and hardware identity covered by those bytes.
    pub modem: ModemFingerprint,
    /// Canonical digest binding immutable provider source and package inputs.
    pub provider_inputs_sha256: String,
}
/// Embedded, hash-bound profile governing qualification, independent of an older receipt.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProviderProfile {
    /// Shared JSON schema version accepted by this consumer.
    pub schema_version: u32,
    /// Pinned modem/PCM contract identifier.
    pub profile_id: String,
    /// Whether the compiled evidence authorizes format eligibility.
    pub qualification: Qualification,
    /// Hardware and firmware for which the contract applies.
    pub modem: ModemFingerprint,
    /// Required ModemManager type of the primary QMI control port.
    pub qmi_primary_type: u32,
    /// Required PCM shape, not proof of current Call configuration.
    pub format: PcmFormat,
    /// Revision of the provider's metadata and lifecycle contract.
    pub contract_revision: u32,
    /// Exact framing/lifecycle records required for a qualified profile.
    pub evidence: Vec<QualificationRecord>,
    #[serde(skip)]
    source_sha256: String,
}
/// Raw-byte binding for one file in the validated provider output.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileRecord {
    /// Confined relative path within the provider output.
    pub file: String,
    /// SHA256 of that file's bytes.
    pub sha256: String,
}
/// One exact Debian package in the validated offline provider closure.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PackageRecord {
    /// Confined relative path to the package archive.
    pub file: String,
    /// SHA256 of the archive, distinct from the daemon executable hash.
    pub sha256: String,
    /// Debian package identifier.
    pub name: String,
    /// Full Debian package version, including the provider revision where applicable.
    pub version: String,
    /// Package architecture, including architecture-independent packages.
    pub architecture: String,
}
/// CI-validated build manifest compiled into the consumer as its expected identity.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProviderManifest {
    /// Shared JSON schema version accepted by this consumer.
    pub schema_version: u32,
    /// Exact source checkout used to produce the manifest.
    pub repo_sha: String,
    /// Build run that produced the validated output.
    pub ci_run_id: String,
    /// Pinned upstream/Debian source version.
    pub source_version: String,
    /// Required provider runtime package version.
    pub package_version: String,
    /// Target architecture of the daemon build.
    pub architecture: String,
    /// SHA256 of the authenticated source/dependency lock bytes.
    pub source_lock_sha256: String,
    /// SHA256 of the ordered local patch-series bytes.
    pub patch_series_sha256: String,
    /// SHA256 of the exact embedded profile bytes.
    pub profile_sha256: String,
    /// SHA256 of the actual packaged daemon executable, not its Debian archive.
    pub daemon_sha256: String,
    /// Complete immutable package closure and its archive hashes.
    pub packages: Vec<PackageRecord>,
    /// Corresponding source and referenced qualification file bindings.
    pub source_files: Vec<FileRecord>,
    /// Build/test evidence files excluded from the immutable input digest.
    pub reports: Vec<FileRecord>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ReceiptProof {
    provider_inputs_sha256: String,
    manifest_sha256: String,
    running: RunningIdentity,
}
/// Current provider snapshot cross-checked against a protected maintenance receipt.
///
/// The installed-file hash alone never proves which executable the process runs.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProviderIdentity {
    /// Installed daemon package version read with fixed dpkg-query arguments.
    pub package_version: String,
    /// Installed daemon package architecture.
    pub architecture: String,
    /// Maintenance-attested running executable hash bound to this exact process.
    pub running_daemon_sha256: String,
    /// Current selected modem's firmware, hardware and plugin identity.
    pub modem: ModemFingerprint,
    /// Current primary control port, checked against the QMI inventory entry.
    pub primary_port: String,
    /// Current port names paired with ModemManager port-type values.
    pub ports: Vec<(String, u32)>,
    /// D-Bus instance identifier, distinguishing bus lifetimes.
    pub bus_id: String,
    /// Captured unique service owner, never a replacement behind a well-known name.
    pub unique_owner: String,
    /// Process identifier resolved for that unique owner.
    pub pid: u32,
    /// Readable process start-time ticks distinguishing PID reuse.
    pub process_start_ticks: u64,
    /// Fresh hash of the fixed installed daemon path.
    pub installed_executable_sha256: String,
    /// Verified raw-byte hash of the receipt's protected copied manifest.
    pub receipt_manifest_sha256: String,
    receipt: ReceiptProof,
}
/// Read-only identity source for the existing native connection and selected modem.
///
/// Production uses fixed package/file reads, readable process stat and a root-owned
/// receipt. It neither reads privileged running-exe bytes nor elevates privileges,
/// restarts the provider or refreshes maintenance attestation.
pub trait ProviderIdentityReader: Send {
    /// Cross-check the captured owner/process before and after reading its identity.
    ///
    /// Returns an error for unreadable, unprotected, missing or changed evidence.
    /// Failure closes eligibility; it is not proof that a native call was released.
    fn read(
        &self,
        connection: &Connection,
        unique_owner: &str,
        modem_path: &str,
    ) -> Result<ProviderIdentity>;
}
/// Privately constructed proof of qualified baseline and exact current format checks.
///
/// This snapshot is not durable admission: callers still enforce the SessionKey,
/// native owner and epoch, current AudioPort/inventory, and native Active fences.
pub struct VerifiedPcm {
    rate: u32,
}
impl VerifiedPcm {
    /// Samples per second proven by the checked current dictionary, without a fallback.
    pub fn sample_rate_hz(&self) -> u32 {
        self.rate
    }
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn hex(value: &str, len: usize) -> bool {
    value.len() == len
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn relative(path: &str) -> bool {
    !path.is_empty()
        && !path.contains(['\\', ':'])
        && !path.chars().any(|c| c.is_control())
        && path
            .split('/')
            .all(|s| !s.is_empty() && s != "." && s != "..")
}
// Python's reviewed ensure_ascii=False, sorted-key compact UTF-8 encoding.
fn canonical(value: &serde_json::Value) -> Result<String> {
    Ok(match value {
        serde_json::Value::Object(values) => {
            let mut keys: Vec<_> = values.keys().collect();
            keys.sort();
            let mut pairs = Vec::new();
            for key in keys {
                pairs.push(format!(
                    "{}:{}",
                    serde_json::to_string(key)?,
                    canonical(&values[key])?
                ));
            }
            format!("{{{}}}", pairs.join(","))
        }
        serde_json::Value::Array(values) => format!(
            "[{}]",
            values
                .iter()
                .map(canonical)
                .collect::<Result<Vec<_>>>()?
                .join(",")
        ),
        other => serde_json::to_string(other)?,
    })
}
impl ProviderManifest {
    fn inputs_sha256(&self) -> Result<String> {
        let mut packages = self.packages.clone();
        packages.sort_by(|a, b| a.name.cmp(&b.name));
        let mut source_files: Vec<_> = self
            .source_files
            .iter()
            .filter(|r| !r.file.starts_with("source/qualification/"))
            .cloned()
            .collect();
        source_files.sort_by(|a, b| a.file.cmp(&b.file));
        let value = serde_json::json!({"source_version":self.source_version,"package_version":self.package_version,
            "architecture":self.architecture,"source_lock_sha256":self.source_lock_sha256,
            "patch_series_sha256":self.patch_series_sha256,"daemon_sha256":self.daemon_sha256,
            "packages":packages,"source_files":source_files});
        Ok(sha256(canonical(&value)?.as_bytes()))
    }
    fn validate(&self) -> Result<()> {
        ensure!(
            self.schema_version == 1
                && hex(&self.repo_sha, 40)
                && !self.ci_run_id.is_empty()
                && self.ci_run_id.bytes().all(|b| b.is_ascii_digit()),
            "Invalid provider manifest identity"
        );
        ensure!(
            self.source_version == SOURCE_VERSION
                && self.package_version == PACKAGE_VERSION
                && self.architecture == "arm64",
            "Unknown provider package"
        );
        for hash in [
            &self.source_lock_sha256,
            &self.patch_series_sha256,
            &self.profile_sha256,
            &self.daemon_sha256,
        ] {
            ensure!(hex(hash, 64), "Invalid provider hash");
        }
        ensure!(
            !self.packages.is_empty() && !self.source_files.is_empty() && !self.reports.is_empty(),
            "Incomplete provider manifest"
        );
        let mut names = BTreeSet::new();
        let mut paths = BTreeSet::from(["manifest.json", "profile.json"]);
        for p in &self.packages {
            ensure!(
                names.insert(&p.name)
                    && paths.insert(p.file.as_str())
                    && relative(&p.file)
                    && hex(&p.sha256, 64)
                    && !p.file.starts_with("source/qualification/")
                    && p.name.len() >= 2
                    && p.name.bytes().all(|b| b.is_ascii_lowercase()
                        || b.is_ascii_digit()
                        || b"+.-".contains(&b))
                    && !p.version.is_empty()
                    && matches!(p.architecture.as_str(), "arm64" | "all"),
                "Invalid provider package row"
            );
        }
        for name in ["modemmanager", "libmm-glib0"] {
            ensure!(
                self.packages.iter().any(|p| p.name == name
                    && p.architecture == "arm64"
                    && p.version == self.package_version),
                "Missing or changed provider runtime package"
            );
        }
        for row in self.source_files.iter().chain(&self.reports) {
            ensure!(
                relative(&row.file) && hex(&row.sha256, 64) && paths.insert(row.file.as_str()),
                "Invalid provider file row"
            );
        }
        ensure!(
            !self
                .reports
                .iter()
                .any(|r| r.file.starts_with("source/qualification/")),
            "Qualification evidence outside source files"
        );
        for (path, hash) in [
            ("source/source-lock.json", &self.source_lock_sha256),
            ("source/patches/series", &self.patch_series_sha256),
        ] {
            ensure!(
                self.source_files
                    .iter()
                    .any(|r| r.file == path && &r.sha256 == hash),
                "Provider source binding mismatch"
            );
        }
        Ok(())
    }
}
impl ProviderProfile {
    fn parse(bytes: &[u8]) -> Result<Self> {
        let mut profile: Self = serde_json::from_slice(bytes)?;
        profile.source_sha256 = sha256(bytes);
        Ok(profile)
    }
    fn validate(&self, expected: &ProviderManifest) -> Result<()> {
        expected.validate()?;
        let pinned: Self = serde_json::from_slice(include_bytes!(
            "../../../deploy/providers/modemmanager/profile.json"
        ))?;
        ensure!(
            self.profile_id == pinned.profile_id && self.modem == pinned.modem,
            "Unknown provider modem profile"
        );
        ensure!(
            self.schema_version == 1
                && self.contract_revision == 1
                && !self.profile_id.is_empty()
                && self.qmi_primary_type == 6
                && self.format.encoding == "pcm"
                && self.format.resolution == "s16le"
                && self.format.rate == 16000
                && self.format.channels == 1,
            "Unknown provider profile contract"
        );
        ensure!(
            self.source_sha256 == expected.profile_sha256,
            "Compiled provider profile hash mismatch"
        );
        let inputs = expected.inputs_sha256()?;
        let mut kinds = BTreeSet::new();
        let mut evidence = BTreeSet::new();
        for record in &self.evidence {
            ensure!(
                matches!(record.kind.as_str(), "framing" | "lifecycle")
                    && kinds.insert(&record.kind)
                    && record.modem == self.modem
                    && record.provider_inputs_sha256 == inputs
                    && relative(&record.path)
                    && record.path.starts_with("source/qualification/")
                    && hex(&record.sha256, 64),
                "Invalid provider qualification record"
            );
            ensure!(
                expected
                    .source_files
                    .iter()
                    .any(|r| r.file == record.path && r.sha256 == record.sha256),
                "Qualification evidence is not bound by expected manifest"
            );
            evidence.insert(record.path.as_str());
        }
        ensure!(
            expected
                .source_files
                .iter()
                .filter(|r| r.file.starts_with("source/qualification/"))
                .map(|r| r.file.as_str())
                .collect::<BTreeSet<_>>()
                == evidence,
            "Unreferenced qualification evidence"
        );
        match self.qualification {
            Qualification::QualificationPending => {
                ensure!(self.evidence.is_empty(), "Pending profile has evidence")
            }
            Qualification::Qualified => ensure!(
                kinds.len() == 2,
                "Missing framing or lifecycle qualification"
            ),
        }
        Ok(())
    }
}
/// Check trusted compiled profile/build bindings against current protected process proof.
///
/// Success permits only baseline admission to Create a keyed UNKNOWN object after
/// clean-idle/key/owner/epoch checks; it requires no Call and cannot authorize
/// Start, Accept or PCM startup. The compiled profile controls qualification even
/// when an older receipt carries identical immutable provider inputs.
///
/// Returns an error on pending qualification, mismatched identity or missing valid
/// receipt proof. This pure check performs no control or native ownership cleanup.
pub fn provider_baseline_eligible(
    profile: &ProviderProfile,
    expected: &ProviderManifest,
    actual: &ProviderIdentity,
) -> Result<()> {
    profile.validate(expected)?;
    ensure!(
        profile.qualification == Qualification::Qualified,
        "GSM provider installed, qualification pending"
    );
    ensure!(
        actual.package_version == expected.package_version
            && actual.architecture == expected.architecture
            && actual.running_daemon_sha256 == expected.daemon_sha256
            && actual.installed_executable_sha256 == expected.daemon_sha256,
        "GSM provider build identity changed"
    );
    ensure!(
        actual.receipt.provider_inputs_sha256 == expected.inputs_sha256()?
            && hex(&actual.receipt_manifest_sha256, 64),
        "GSM provider receipt inputs changed"
    );
    ensure!(
        actual.receipt_manifest_sha256 == actual.receipt.manifest_sha256
            && actual.receipt.running
                == RunningIdentity {
                    bus_id: actual.bus_id.clone(),
                    unique_owner: actual.unique_owner.clone(),
                    pid: actual.pid,
                    process_start_ticks: actual.process_start_ticks,
                    running_daemon_sha256: actual.running_daemon_sha256.clone(),
                    installed_executable_sha256: actual.installed_executable_sha256.clone(),
                    package_version: actual.package_version.clone(),
                    architecture: actual.architecture.clone()
                },
        "GSM provider process differs from protected receipt"
    );
    ensure!(
        !actual.bus_id.is_empty()
            && actual.unique_owner.starts_with(':')
            && actual.pid != 0
            && actual.process_start_ticks != 0,
        "Missing running provider identity"
    );
    ensure!(
        actual.modem == profile.modem
            && actual
                .ports
                .iter()
                .any(|(p, t)| p == &actual.primary_port && *t == profile.qmi_primary_type),
        "GSM modem fingerprint or QMI primary port changed"
    );
    Ok(())
}
/// Check baseline eligibility and a freshly read exact Call `pcm`/`s16le`/16000 dictionary.
///
/// The caller binds that dictionary to the current Call path and SessionKey and
/// retains native owner/epoch fences across preparation and control. Success does
/// not establish native Active or authorize audio without current endpoint proof.
/// The caller must also freshly check native voice readiness (modem state,
/// lock and emergency policy) before control.
/// Missing, mistyped or incompatible metadata returns an error without a rate
/// fallback or any claim of native release; this function performs no D-Bus I/O.
pub fn eligible_format(
    profile: &ProviderProfile,
    expected: &ProviderManifest,
    actual: &ProviderIdentity,
    format: &HashMap<String, zvariant::OwnedValue>,
) -> Result<VerifiedPcm> {
    provider_baseline_eligible(profile, expected, actual)?;
    ensure!(
        current_format_matches(format),
        "GSM current Call audio format unavailable"
    );
    Ok(VerifiedPcm { rate: 16000 })
}
pub(crate) fn current_format_matches(format: &HashMap<String, zvariant::OwnedValue>) -> bool {
    format.len() == 3
        && format
            .get("encoding")
            .and_then(|v| <&str>::try_from(v).ok())
            == Some("pcm")
        && format
            .get("resolution")
            .and_then(|v| <&str>::try_from(v).ok())
            == Some("s16le")
        && format.get("rate").and_then(|v| u32::try_from(v).ok()) == Some(16000)
}

pub(crate) struct ProviderGate {
    profile: ProviderProfile,
    expected: Option<ProviderManifest>,
    reader: Box<dyn ProviderIdentityReader>,
}
impl Default for ProviderGate {
    fn default() -> Self {
        Self {
            profile: ProviderProfile::parse(include_bytes!(
                "../../../deploy/providers/modemmanager/profile.json"
            ))
            .expect("tracked provider profile"),
            expected: option_env!("YOYOPOD_MM_BUILD_MANIFEST")
                .and_then(|v| serde_json::from_str(v).ok()),
            reader: Box::new(InstalledIdentityReader),
        }
    }
}
impl ProviderGate {
    pub(crate) fn read(
        &self,
        connection: &Connection,
        owner: &str,
        modem: &str,
    ) -> Result<ProviderIdentity> {
        let expected = self
            .expected
            .as_ref()
            .context("Compiled provider manifest absent or invalid")?;
        // Reject pending builds before any filesystem/subprocess probe.
        self.profile.validate(expected)?;
        ensure!(
            self.profile.qualification == Qualification::Qualified,
            "GSM provider installed, qualification pending"
        );
        let actual = self.reader.read(connection, owner, modem)?;
        provider_baseline_eligible(&self.profile, expected, &actual)?;
        Ok(actual)
    }
    pub(crate) fn format(
        &self,
        actual: &ProviderIdentity,
        format: &HashMap<String, zvariant::OwnedValue>,
    ) -> Result<VerifiedPcm> {
        eligible_format(
            &self.profile,
            self.expected
                .as_ref()
                .context("Compiled provider manifest absent")?,
            actual,
            format,
        )
    }
}

struct InstalledIdentityReader;
impl ProviderIdentityReader for InstalledIdentityReader {
    fn read(
        &self,
        connection: &Connection,
        unique_owner: &str,
        modem_path: &str,
    ) -> Result<ProviderIdentity> {
        read_installed_identity(connection, unique_owner, modem_path)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
struct RunningIdentity {
    bus_id: String,
    unique_owner: String,
    pid: u32,
    process_start_ticks: u64,
    running_daemon_sha256: String,
    installed_executable_sha256: String,
    package_version: String,
    architecture: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Receipt {
    schema_version: u32,
    manifest: String,
    profile: String,
    manifest_sha256: String,
    profile_sha256: String,
    running_identity: RunningIdentity,
}
trait IdentityFiles {
    fn receipt_file(&self, name: &str) -> Result<Vec<u8>>;
    fn package(&self) -> Result<(String, String)>;
    fn start_ticks(&self, pid: u32) -> Result<u64>;
    fn executable_hash(&self) -> Result<String>;
}
struct NormalAccountFiles;
fn protected_owner_mode(uid: u32, mode: u32) -> bool {
    uid == 0 && mode & 0o022 == 0
}
impl IdentityFiles for NormalAccountFiles {
    fn receipt_file(&self, name: &str) -> Result<Vec<u8>> {
        ensure!(
            matches!(name, "installed.json" | "manifest.json" | "profile.json"),
            "Invalid receipt filename"
        );
        protected_bytes(&std::path::Path::new(RECEIPT_DIR).join(name))
    }
    fn package(&self) -> Result<(String, String)> {
        // No shell, caller-supplied argv, sudo, or running-exe access.
        let result = std::process::Command::new("/usr/bin/dpkg-query")
            .args([
                "-W",
                "-f=${db:Status-Status}\\t${Version}\\t${Architecture}\\n",
                "modemmanager",
            ])
            .output()?;
        ensure!(result.status.success(), "Provider package query failed");
        let output = String::from_utf8(result.stdout)?;
        let fields: Vec<_> = output.trim_end().split('\t').collect();
        ensure!(
            fields.len() == 3 && fields[0] == "installed",
            "Provider package not installed"
        );
        Ok((fields[1].into(), fields[2].into()))
    }
    fn start_ticks(&self, pid: u32) -> Result<u64> {
        parse_start_ticks(&std::fs::read_to_string(format!("/proc/{pid}/stat"))?, pid)
    }
    fn executable_hash(&self) -> Result<String> {
        Ok(sha256(&std::fs::read("/usr/sbin/ModemManager")?))
    }
}
#[cfg(unix)]
fn protected_bytes(path: &std::path::Path) -> Result<Vec<u8>> {
    use std::io::Read;
    use std::os::unix::fs::MetadataExt;
    for parent in path.ancestors().skip(1) {
        let m = std::fs::symlink_metadata(parent)?;
        ensure!(
            m.is_dir() && !m.file_type().is_symlink() && protected_owner_mode(m.uid(), m.mode()),
            "Unprotected provider receipt directory"
        );
    }
    let before = std::fs::symlink_metadata(path)?;
    ensure!(
        before.is_file()
            && !before.file_type().is_symlink()
            && protected_owner_mode(before.uid(), before.mode())
            && before.len() <= 4 * 1024 * 1024,
        "Unprotected provider receipt file"
    );
    let mut file = std::fs::File::open(path)?;
    let opened = file.metadata()?;
    ensure!(
        opened.dev() == before.dev() && opened.ino() == before.ino(),
        "Provider receipt substituted"
    );
    let mut bytes = Vec::new();
    file.by_ref()
        .take(4 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    ensure!(
        bytes.len() <= 4 * 1024 * 1024
            && after.dev() == before.dev()
            && after.ino() == before.ino()
            && protected_owner_mode(after.uid(), after.mode())
            && after.len() == before.len()
            && after.mtime() == before.mtime()
            && after.mtime_nsec() == before.mtime_nsec(),
        "Provider receipt changed during read"
    );
    Ok(bytes)
}
#[cfg(not(unix))]
fn protected_bytes(_path: &std::path::Path) -> Result<Vec<u8>> {
    anyhow::bail!("Protected provider receipt requires Linux")
}
fn parse_start_ticks(stat: &str, pid: u32) -> Result<u64> {
    let (prefix, fields) = stat.rsplit_once(')').context("Malformed process stat")?;
    ensure!(
        prefix.split_once('(').map(|(p, _)| p.trim()) == Some(pid.to_string().as_str()),
        "Process stat PID mismatch"
    );
    let ticks = fields
        .split_whitespace()
        .nth(19)
        .context("Missing process start ticks")?
        .parse()?;
    ensure!(ticks != 0, "Missing process start ticks");
    Ok(ticks)
}
fn dbus_identity(connection: &Connection, owner: &str) -> Result<(String, String, u32)> {
    zbus::names::UniqueName::try_from(owner)?;
    let bus = Proxy::new(
        connection,
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
    )?;
    let bus_id = bus.call("GetId", &())?;
    let current: String = bus.call("GetNameOwner", &("org.freedesktop.ModemManager1",))?;
    ensure!(current == owner, "Provider owner changed");
    Ok((
        bus_id,
        current,
        bus.call("GetConnectionUnixProcessID", &(owner,))?,
    ))
}
type ModemIdentity = (ModemFingerprint, String, Vec<(String, u32)>);
fn read_modem(connection: &Connection, owner: &str, modem: &str) -> Result<ModemIdentity> {
    let proxy: Proxy<'_> = zbus::blocking::proxy::Builder::new(connection)
        .destination(owner)?
        .path(modem)?
        .interface(MODEM_INTERFACE)?
        .cache_properties(zbus::proxy::CacheProperties::No)
        .build()?;
    let fingerprint = ModemFingerprint {
        manufacturer: proxy.get_property("Manufacturer")?,
        model: proxy.get_property("Model")?,
        revision: proxy.get_property("Revision")?,
        hardware_revision: proxy.get_property("HardwareRevision")?,
        plugin: proxy.get_property("Plugin")?,
    };
    let mut ports: Vec<(String, u32)> = proxy.get_property("Ports")?;
    ports.sort();
    Ok((fingerprint, proxy.get_property("PrimaryPort")?, ports))
}
fn verified_receipt(
    files: &dyn IdentityFiles,
    current: &RunningIdentity,
) -> Result<(String, ReceiptProof)> {
    let receipt: Receipt = serde_json::from_slice(&files.receipt_file("installed.json")?)?;
    ensure!(
        receipt.schema_version == 1
            && receipt.manifest == "manifest.json"
            && receipt.profile == "profile.json"
            && hex(&receipt.manifest_sha256, 64)
            && hex(&receipt.profile_sha256, 64),
        "Invalid provider receipt"
    );
    let manifest = files.receipt_file("manifest.json")?;
    let profile = files.receipt_file("profile.json")?;
    ensure!(
        sha256(&manifest) == receipt.manifest_sha256 && sha256(&profile) == receipt.profile_sha256,
        "Provider receipt copy hash mismatch"
    );
    let manifest: ProviderManifest = serde_json::from_slice(&manifest)?;
    let profile = ProviderProfile::parse(&profile)?;
    profile.validate(&manifest)?;
    ensure!(
        receipt.profile_sha256 == manifest.profile_sha256
            && &receipt.running_identity == current
            && current.running_daemon_sha256 == manifest.daemon_sha256
            && current.installed_executable_sha256 == manifest.daemon_sha256
            && current.package_version == manifest.package_version
            && current.architecture == manifest.architecture,
        "Provider running maintenance attestation changed"
    );
    Ok((
        receipt.manifest_sha256.clone(),
        ReceiptProof {
            provider_inputs_sha256: manifest.inputs_sha256()?,
            manifest_sha256: receipt.manifest_sha256,
            running: current.clone(),
        },
    ))
}

fn read_installed_identity(
    connection: &Connection,
    owner: &str,
    modem: &str,
) -> Result<ProviderIdentity> {
    read_identity_with_files(connection, owner, modem, &NormalAccountFiles)
}
fn read_identity_with_files(
    connection: &Connection,
    owner: &str,
    modem: &str,
    files: &dyn IdentityFiles,
) -> Result<ProviderIdentity> {
    let (bus_id, unique_owner, pid) = dbus_identity(connection, owner)?;
    let (package_version, architecture) = files.package()?;
    let process_start_ticks = files.start_ticks(pid)?;
    let installed_executable_sha256 = files.executable_hash()?;
    // Read attested running hash only from the protected receipt. It is never
    // inferred from the installed filename or /proc/<pid>/exe.
    let receipt: Receipt = serde_json::from_slice(&files.receipt_file("installed.json")?)?;
    let current = RunningIdentity {
        bus_id: bus_id.clone(),
        unique_owner: unique_owner.clone(),
        pid,
        process_start_ticks,
        package_version: package_version.clone(),
        architecture: architecture.clone(),
        installed_executable_sha256: installed_executable_sha256.clone(),
        running_daemon_sha256: receipt.running_identity.running_daemon_sha256,
    };
    let (receipt_manifest_sha256, receipt) = verified_receipt(files, &current)?;
    let identity = read_modem(connection, owner, modem)?;
    ensure!(
        dbus_identity(connection, owner)? == (bus_id.clone(), unique_owner.clone(), pid)
            && files.start_ticks(pid)? == process_start_ticks
            && files.package()? == (package_version.clone(), architecture.clone())
            && files.executable_hash()? == installed_executable_sha256
            && read_modem(connection, owner, modem)? == identity,
        "Provider identity changed during read"
    );
    Ok(ProviderIdentity {
        package_version,
        architecture,
        running_daemon_sha256: current.running_daemon_sha256,
        modem: identity.0,
        primary_port: identity.1,
        ports: identity.2,
        bus_id,
        unique_owner,
        pid,
        process_start_ticks,
        installed_executable_sha256,
        receipt_manifest_sha256,
        receipt,
    })
}

#[cfg(test)]
impl ProviderManifest {
    pub(crate) fn test_fixture() -> Self {
        // Synthetic hashes throughout. These are never production package proof.
        Self {
            schema_version: 1,
            repo_sha: "a".repeat(40),
            ci_run_id: "1".into(),
            source_version: SOURCE_VERSION.into(),
            package_version: PACKAGE_VERSION.into(),
            architecture: "arm64".into(),
            source_lock_sha256: "1".repeat(64),
            patch_series_sha256: "2".repeat(64),
            profile_sha256: "0".repeat(64),
            daemon_sha256: "3".repeat(64),
            packages: ["modemmanager", "libmm-glib0"]
                .into_iter()
                .map(|name| PackageRecord {
                    file: format!("packages/{name}.deb"),
                    sha256: "4".repeat(64),
                    name: name.into(),
                    version: PACKAGE_VERSION.into(),
                    architecture: "arm64".into(),
                })
                .collect(),
            source_files: vec![
                FileRecord {
                    file: "source/synthetic.txt".into(),
                    sha256: "5".repeat(64),
                },
                FileRecord {
                    file: "source/source-lock.json".into(),
                    sha256: "1".repeat(64),
                },
                FileRecord {
                    file: "source/patches/series".into(),
                    sha256: "2".repeat(64),
                },
            ],
            reports: vec![FileRecord {
                file: "reports/synthetic.txt".into(),
                sha256: "6".repeat(64),
            }],
        }
    }
}
#[cfg(test)]
impl ProviderProfile {
    pub(crate) fn test_fixture(qualification: Qualification) -> Self {
        let mut profile = Self::parse(include_bytes!(
            "../../../deploy/providers/modemmanager/profile.json"
        ))
        .unwrap();
        profile.qualification = qualification;
        if profile.qualification == Qualification::Qualified {
            for kind in ["framing", "lifecycle"] {
                profile.evidence.push(QualificationRecord {
                    kind: kind.into(),
                    path: format!("source/qualification/synthetic-{kind}.txt"),
                    sha256: "7".repeat(64),
                    modem: profile.modem.clone(),
                    provider_inputs_sha256: ProviderManifest::test_fixture()
                        .inputs_sha256()
                        .unwrap(),
                });
            }
        }
        profile.source_sha256 = sha256(&serde_json::to_vec(&profile).unwrap());
        profile
    }
}
#[cfg(test)]
impl ProviderIdentity {
    pub(crate) fn test_fixture(expected: &ProviderManifest) -> Self {
        let running = RunningIdentity {
            bus_id: "synthetic-bus".into(),
            unique_owner: ":1.1".into(),
            pid: 42,
            process_start_ticks: 123,
            running_daemon_sha256: expected.daemon_sha256.clone(),
            installed_executable_sha256: expected.daemon_sha256.clone(),
            package_version: expected.package_version.clone(),
            architecture: expected.architecture.clone(),
        };
        Self {
            package_version: running.package_version.clone(),
            architecture: running.architecture.clone(),
            running_daemon_sha256: running.running_daemon_sha256.clone(),
            modem: ProviderProfile::test_fixture(Qualification::Qualified).modem,
            primary_port: "cdc-wdm0".into(),
            ports: vec![("cdc-wdm0".into(), 6), ("ttyUSB9".into(), 8)],
            bus_id: running.bus_id.clone(),
            unique_owner: running.unique_owner.clone(),
            pid: running.pid,
            process_start_ticks: running.process_start_ticks,
            installed_executable_sha256: running.installed_executable_sha256.clone(),
            receipt_manifest_sha256: "8".repeat(64),
            receipt: ReceiptProof {
                provider_inputs_sha256: expected.inputs_sha256().unwrap(),
                manifest_sha256: "8".repeat(64),
                running,
            },
        }
    }
}
#[cfg(test)]
impl ProviderGate {
    pub(crate) fn test_fixture() -> Self {
        struct SyntheticReader(ProviderManifest);
        impl ProviderIdentityReader for SyntheticReader {
            fn read(&self, _: &Connection, _: &str, _: &str) -> Result<ProviderIdentity> {
                Ok(ProviderIdentity::test_fixture(&self.0))
            }
        }
        let profile = ProviderProfile::test_fixture(Qualification::Qualified);
        let mut expected = ProviderManifest::test_fixture();
        expected.profile_sha256 = profile.source_sha256.clone();
        expected
            .source_files
            .extend(profile.evidence.iter().map(|e| FileRecord {
                file: e.path.clone(),
                sha256: e.sha256.clone(),
            }));
        Self {
            profile,
            reader: Box::new(SyntheticReader(expected.clone())),
            expected: Some(expected),
        }
    }
}

#[cfg(test)]
pub(crate) mod gsm_provider_tests {
    use super::*;
    fn format() -> HashMap<String, zvariant::OwnedValue> {
        HashMap::from([
            (
                "encoding".into(),
                zvariant::OwnedValue::from(zvariant::Str::from("pcm")),
            ),
            (
                "resolution".into(),
                zvariant::OwnedValue::from(zvariant::Str::from("s16le")),
            ),
            ("rate".into(), zvariant::OwnedValue::from(16000u32)),
        ])
    }
    #[test]
    fn gsm_provider_pending_dictionary_never_enables_control() {
        let mut gate = ProviderGate::test_fixture();
        gate.profile = ProviderProfile::test_fixture(Qualification::QualificationPending);
        let expected = gate.expected.as_mut().unwrap();
        expected.profile_sha256 = gate.profile.source_sha256.clone();
        expected
            .source_files
            .retain(|r| !r.file.starts_with("source/qualification/"));
        let actual = ProviderIdentity::test_fixture(expected);
        assert!(eligible_format(&gate.profile, expected, &actual, &format()).is_err());
        assert!(provider_baseline_eligible(&gate.profile, expected, &actual).is_err());
    }
    #[test]
    fn gsm_provider_qualified_idle_needs_no_call_but_format_requires_current_dictionary() {
        let gate = ProviderGate::test_fixture();
        let expected = gate.expected.as_ref().unwrap();
        let actual = ProviderIdentity::test_fixture(expected);
        provider_baseline_eligible(&gate.profile, expected, &actual).unwrap();
        assert_eq!(
            eligible_format(&gate.profile, expected, &actual, &format())
                .unwrap()
                .sample_rate_hz(),
            16000
        );
        for field in ["encoding", "resolution", "rate"] {
            let mut missing = format();
            missing.remove(field);
            assert!(eligible_format(&gate.profile, expected, &actual, &missing).is_err());
            let mut wrong = format();
            wrong.insert(field.into(), zvariant::OwnedValue::from(1u32));
            assert!(eligible_format(&gate.profile, expected, &actual, &wrong).is_err());
        }
        let mut narrow = format();
        narrow.insert("rate".into(), zvariant::OwnedValue::from(8000u32));
        assert!(eligible_format(&gate.profile, expected, &actual, &narrow).is_err());
        let mut string_rate = format();
        string_rate.insert(
            "rate".into(),
            zvariant::OwnedValue::from(zvariant::Str::from("16000")),
        );
        assert!(eligible_format(&gate.profile, expected, &actual, &string_rate).is_err());
    }
    #[test]
    fn gsm_provider_changed_identity_or_evidence_fails_closed() {
        let gate = ProviderGate::test_fixture();
        let expected = gate.expected.as_ref().unwrap();
        let original = ProviderIdentity::test_fixture(expected);
        type IdentityMutation = Box<dyn Fn(&mut ProviderIdentity)>;
        let mutations: Vec<IdentityMutation> = vec![
            Box::new(|i| i.modem.revision.push('x')),
            Box::new(|i| i.modem.hardware_revision.push('x')),
            Box::new(|i| i.modem.manufacturer.push('x')),
            Box::new(|i| i.modem.model.push('x')),
            Box::new(|i| i.modem.plugin = "generic".into()),
            Box::new(|i| i.primary_port = "ttyUSB2".into()),
            Box::new(|i| i.ports.clear()),
            Box::new(|i| i.package_version = "unknown".into()),
            Box::new(|i| i.architecture = "amd64".into()),
            Box::new(|i| i.installed_executable_sha256 = "9".repeat(64)),
            Box::new(|i| i.running_daemon_sha256 = "9".repeat(64)),
            Box::new(|i| i.bus_id.push('x')),
            Box::new(|i| i.unique_owner = ":1.9".into()),
            Box::new(|i| i.pid += 1),
            Box::new(|i| i.process_start_ticks += 1),
            Box::new(|i| i.receipt_manifest_sha256 = "9".repeat(64)),
            Box::new(|i| i.receipt.provider_inputs_sha256 = "9".repeat(64)),
        ];
        for mutate in mutations {
            let mut actual = original.clone();
            mutate(&mut actual);
            assert!(provider_baseline_eligible(&gate.profile, expected, &actual).is_err());
        }
        for kind in ["framing", "lifecycle"] {
            let mut profile = gate.profile.clone();
            profile.evidence.retain(|r| r.kind != kind);
            assert!(provider_baseline_eligible(&profile, expected, &original).is_err());
        }
        let mut absent = ProviderGate::test_fixture();
        absent.expected = None;
        assert!(absent.format(&original, &format()).is_err());
    }
    #[test]
    fn gsm_provider_digest_matches_reviewed_python_utf8_vector() {
        let literal = concat!("{\"architecture\":\"arm64\",\"daemon_sha256\":\"3333333333333333333333333333333333333333333333333333333333333333\",",
            "\"package_version\":\"synthetic-package-1\",\"packages\":[{\"architecture\":\"arm64\",\"file\":\"packages/synthetic.deb\",\"name\":\"synthetic-package\",\"sha256\":\"4444444444444444444444444444444444444444444444444444444444444444\",\"version\":\"1\"}],",
            "\"patch_series_sha256\":\"2222222222222222222222222222222222222222222222222222222222222222\",",
            "\"source_files\":[{\"file\":\"source/a.txt\",\"sha256\":\"5555555555555555555555555555555555555555555555555555555555555555\"},{\"file\":\"source/fixture-é.txt\",\"sha256\":\"6666666666666666666666666666666666666666666666666666666666666666\"}],",
            "\"source_lock_sha256\":\"1111111111111111111111111111111111111111111111111111111111111111\",\"source_version\":\"synthetic-source-1\"}");
        assert_eq!(literal.len(), 775);
        let expected = "21e0c1ab181642a36b457c7e15ee3b78dfec498c3bfe61d38a052f8ce5579f7e";
        assert_eq!(sha256(literal.as_bytes()), expected);
        let value: serde_json::Value = serde_json::from_str(literal).unwrap();
        assert_eq!(canonical(&value).unwrap(), literal);
        let mut manifest = ProviderManifest::test_fixture();
        manifest.source_version = value["source_version"].as_str().unwrap().into();
        manifest.package_version = value["package_version"].as_str().unwrap().into();
        manifest.packages = serde_json::from_value(value["packages"].clone()).unwrap();
        manifest.source_files = serde_json::from_value(value["source_files"].clone()).unwrap();
        assert_eq!(manifest.inputs_sha256().unwrap(), expected);
        manifest.source_files.reverse();
        manifest.source_files.push(FileRecord {
            file: "source/qualification/synthetic.txt".into(),
            sha256: "7".repeat(64),
        });
        assert_eq!(manifest.inputs_sha256().unwrap(), expected);
    }

    struct SyntheticFiles {
        files: HashMap<String, Vec<u8>>,
        deny: Option<&'static str>,
        current: RunningIdentity,
    }
    impl IdentityFiles for SyntheticFiles {
        fn receipt_file(&self, name: &str) -> Result<Vec<u8>> {
            ensure!(
                self.deny != Some(name),
                "Fixture unprotected or unreadable receipt"
            );
            self.files
                .get(name)
                .cloned()
                .context("Fixture missing receipt")
        }
        fn package(&self) -> Result<(String, String)> {
            Ok((
                self.current.package_version.clone(),
                self.current.architecture.clone(),
            ))
        }
        fn start_ticks(&self, _pid: u32) -> Result<u64> {
            ensure!(self.deny != Some("stat"), "Fixture denied stat");
            Ok(self.current.process_start_ticks)
        }
        fn executable_hash(&self) -> Result<String> {
            ensure!(self.deny != Some("executable"), "Fixture denied executable");
            Ok(self.current.installed_executable_sha256.clone())
        }
    }
    fn receipt_fixture() -> (ProviderGate, SyntheticFiles) {
        let gate = ProviderGate::test_fixture();
        let expected = gate.expected.as_ref().unwrap();
        let actual = ProviderIdentity::test_fixture(expected);
        // A genuinely pending installed receipt can be carried forward by a
        // qualified compiled profile when immutable package/source bytes agree.
        let profile = ProviderProfile::test_fixture(Qualification::QualificationPending);
        let profile_bytes = serde_json::to_vec(&profile).unwrap();
        let mut manifest = expected.clone();
        manifest.profile_sha256 = sha256(&profile_bytes);
        manifest
            .source_files
            .retain(|r| !r.file.starts_with("source/qualification/"));
        manifest.repo_sha = "b".repeat(40);
        manifest.ci_run_id = "2".into();
        let manifest_bytes = serde_json::to_vec(&manifest).unwrap();
        let current = actual.receipt.running;
        let running = serde_json::json!({"bus_id":current.bus_id,"unique_owner":current.unique_owner,"pid":current.pid,
            "process_start_ticks":current.process_start_ticks,"running_daemon_sha256":current.running_daemon_sha256,
            "installed_executable_sha256":current.installed_executable_sha256,"package_version":current.package_version,"architecture":current.architecture});
        let receipt = serde_json::json!({"schema_version":1,"manifest":"manifest.json","profile":"profile.json",
            "manifest_sha256":sha256(&manifest_bytes),"profile_sha256":sha256(&profile_bytes),"running_identity":running});
        (
            gate,
            SyntheticFiles {
                files: HashMap::from([
                    (
                        "installed.json".into(),
                        serde_json::to_vec(&receipt).unwrap(),
                    ),
                    ("manifest.json".into(), manifest_bytes),
                    ("profile.json".into(), profile_bytes),
                ]),
                deny: None,
                current,
            },
        )
    }
    #[test]
    fn gsm_provider_pending_receipt_carries_only_identical_immutable_inputs() {
        let (gate, files) = receipt_fixture();
        let (manifest_hash, proof) = verified_receipt(&files, &files.current).unwrap();
        let mut actual = ProviderIdentity::test_fixture(gate.expected.as_ref().unwrap());
        actual.receipt_manifest_sha256 = manifest_hash;
        actual.receipt = proof;
        provider_baseline_eligible(&gate.profile, gate.expected.as_ref().unwrap(), &actual)
            .unwrap();
        let mut changed = gate.expected.unwrap();
        changed.source_lock_sha256 = "f".repeat(64);
        assert!(provider_baseline_eligible(&gate.profile, &changed, &actual).is_err());
    }
    #[test]
    fn gsm_provider_receipt_tampering_missing_attestation_and_process_changes_rejected() {
        for name in ["installed.json", "manifest.json", "profile.json"] {
            let (_, mut files) = receipt_fixture();
            files.files.remove(name);
            assert!(verified_receipt(&files, &files.current).is_err());
            let (_, mut files) = receipt_fixture();
            files.deny = Some(name);
            assert!(verified_receipt(&files, &files.current).is_err());
            let (_, mut files) = receipt_fixture();
            files.files.get_mut(name).unwrap().push(b'x');
            assert!(verified_receipt(&files, &files.current).is_err());
        }
        for field in [
            "bus_id",
            "unique_owner",
            "pid",
            "process_start_ticks",
            "running_daemon_sha256",
            "installed_executable_sha256",
            "package_version",
            "architecture",
        ] {
            let (_, mut files) = receipt_fixture();
            let mut receipt: serde_json::Value =
                serde_json::from_slice(&files.files["installed.json"]).unwrap();
            receipt["running_identity"][field] = if matches!(field, "pid" | "process_start_ticks") {
                serde_json::json!(999)
            } else {
                serde_json::json!("changed")
            };
            files.files.insert(
                "installed.json".into(),
                serde_json::to_vec(&receipt).unwrap(),
            );
            assert!(verified_receipt(&files, &files.current).is_err(), "{field}");
        }
        for field in ["running_identity", "manifest_sha256", "profile_sha256"] {
            let (_, mut files) = receipt_fixture();
            let mut receipt: serde_json::Value =
                serde_json::from_slice(&files.files["installed.json"]).unwrap();
            receipt.as_object_mut().unwrap().remove(field);
            files.files.insert(
                "installed.json".into(),
                serde_json::to_vec(&receipt).unwrap(),
            );
            assert!(verified_receipt(&files, &files.current).is_err());
        }
        for field in ["manifest", "profile"] {
            let (_, mut files) = receipt_fixture();
            let mut receipt: serde_json::Value =
                serde_json::from_slice(&files.files["installed.json"]).unwrap();
            receipt[field] = serde_json::json!("../substituted.json");
            files.files.insert(
                "installed.json".into(),
                serde_json::to_vec(&receipt).unwrap(),
            );
            assert!(verified_receipt(&files, &files.current).is_err());
        }
        let (_, mut files) = receipt_fixture();
        files.deny = Some("stat");
        assert!(files.start_ticks(42).is_err());
        files.deny = Some("executable");
        assert!(files.executable_hash().is_err());
    }
    #[test]
    fn gsm_provider_stat_parser_handles_parentheses_without_reading_exe() {
        let stat = format!(
            "42 (name (with) spaces) S {} 123 0",
            vec!["0"; 18].join(" ")
        );
        assert_eq!(parse_start_ticks(&stat, 42).unwrap(), 123);
        assert!(parse_start_ticks(&stat, 43).is_err());
        assert!(parse_start_ticks("42 (short) S", 42).is_err());
    }
    #[test]
    fn gsm_provider_receipt_ownership_and_writable_modes_fail_closed() {
        assert!(protected_owner_mode(0, 0o100644));
        assert!(protected_owner_mode(0, 0o40755));
        for (uid, mode) in [
            (1000, 0o100644),
            (0, 0o100664),
            (0, 0o100646),
            (0, 0o40775),
            (0, 0o40757),
        ] {
            assert!(!protected_owner_mode(uid, mode));
        }
    }
    pub(crate) fn normal_account_identity_fixture(
        connection: &Connection,
        owner: &str,
        modem: &str,
    ) {
        let (gate, mut files) = receipt_fixture();
        let (bus, unique, pid) = dbus_identity(connection, owner).unwrap();
        files.current.bus_id = bus;
        files.current.unique_owner = unique;
        files.current.pid = pid;
        let mut receipt: serde_json::Value =
            serde_json::from_slice(&files.files["installed.json"]).unwrap();
        receipt["running_identity"]["bus_id"] = serde_json::json!(files.current.bus_id);
        receipt["running_identity"]["unique_owner"] = serde_json::json!(files.current.unique_owner);
        receipt["running_identity"]["pid"] = serde_json::json!(pid);
        files.files.insert(
            "installed.json".into(),
            serde_json::to_vec(&receipt).unwrap(),
        );
        let actual = read_identity_with_files(connection, owner, modem, &files).unwrap();
        provider_baseline_eligible(&gate.profile, gate.expected.as_ref().unwrap(), &actual)
            .unwrap();
        for denied in [
            "stat",
            "executable",
            "installed.json",
            "manifest.json",
            "profile.json",
        ] {
            files.deny = Some(denied);
            assert!(
                read_identity_with_files(connection, owner, modem, &files).is_err(),
                "{denied}"
            );
        }
        files.deny = None;
        for field in [
            "bus_id",
            "unique_owner",
            "pid",
            "process_start_ticks",
            "running_daemon_sha256",
        ] {
            let original = files.files["installed.json"].clone();
            let mut receipt: serde_json::Value = serde_json::from_slice(&original).unwrap();
            receipt["running_identity"][field] = if matches!(field, "pid" | "process_start_ticks") {
                serde_json::json!(999)
            } else {
                serde_json::json!("changed")
            };
            files.files.insert(
                "installed.json".into(),
                serde_json::to_vec(&receipt).unwrap(),
            );
            assert!(read_identity_with_files(connection, owner, modem, &files).is_err());
            files.files.insert("installed.json".into(), original);
        }
    }
}
