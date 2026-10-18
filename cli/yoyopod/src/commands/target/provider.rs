//! Explicit provider maintenance. Verified bytes stay private until the locked
//! transaction has captured a complete offline rollback and proved no calls.
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::Path;
use std::process::Command;

use anyhow::{bail, ensure, Context, Result};
use flate2::read::MultiGzDecoder;
use serde::de::{self, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use tempfile::TempDir;

use crate::paths::{LanePaths, PiPaths};
use crate::quoting::shell_quote;
use crate::repo::current_repo_root;
use crate::ssh::{run_remote_capture, RemoteWorkdir};

use super::{deploy, ops, TargetContext};

const TRANSACTION: &str =
    include_str!("../../../../../deploy/providers/modemmanager/deploy/transaction.sh");
const UDEV_RULE: &str = include_str!("../../../../../deploy/udev/77-yoyopod-sim7600.rules");
const BINARIES: [&str; 9] = [
    "device/cloud/build/yoyopod-cloud-host",
    "device/media/build/yoyopod-media-host",
    "device/network/build/yoyopod-network-host",
    "device/onpi/build/yoyopod-on-pi",
    "device/power/build/yoyopod-power-host",
    "device/runtime/build/yoyopod-runtime",
    "device/speech/build/yoyopod-speech-host",
    "device/ui/build/yoyopod-ui-host",
    "device/voip/build/yoyopod-voip-host",
];
const PROVIDER: &str = "providers/modemmanager/";

#[derive(Clone, Copy)]
struct ArchiveLimits {
    compressed: u64,
    expanded: u64,
    member: u64,
    json: u64,
    members: usize,
    padding: usize,
}
const ARCHIVE_LIMITS: ArchiveLimits = ArchiveLimits {
    compressed: 1024 * 1024 * 1024,
    expanded: 2 * 1024 * 1024 * 1024,
    member: 512 * 1024 * 1024,
    json: 4 * 1024 * 1024,
    members: 8192,
    padding: 1024 * 1024,
};

// Count the complete decompressed stream, including headers and padding. A
// single-byte probe distinguishes an exact-budget EOF from further payload.
struct ExpandedReader<R> {
    inner: R,
    remaining: u64,
}
impl<R: Read> Read for ExpandedReader<R> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        if output.is_empty() {
            return Ok(0);
        }
        if self.remaining == 0 {
            return if self.inner.read(&mut [0])? == 0 {
                Ok(0)
            } else {
                Err(io::Error::other("expanded archive budget exceeded"))
            };
        }
        let size = output
            .len()
            .min(usize::try_from(self.remaining).unwrap_or(usize::MAX));
        let count = self.inner.read(&mut output[..size])?;
        self.remaining -= count as u64;
        Ok(count)
    }
}
type CheckedArchive = tar::Archive<ExpandedReader<MultiGzDecoder<io::Take<File>>>>;
fn open_archive(path: &Path, limits: ArchiveLimits) -> Result<CheckedArchive> {
    let input = File::open(path)?;
    ensure!(
        input.metadata()?.len() <= limits.compressed,
        "compressed archive budget exceeded"
    );
    Ok(tar::Archive::new(ExpandedReader {
        inner: MultiGzDecoder::new(input.take(limits.compressed)),
        remaining: limits.expanded,
    }))
}
fn check_member(header: &tar::Header, index: usize, limits: ArchiveLimits) -> Result<()> {
    ensure!(
        index < limits.members,
        "archive member count budget exceeded"
    );
    ensure!(
        header.size()? <= limits.member,
        "archive member budget exceeded"
    );
    Ok(())
}
fn finish_archive(archive: CheckedArchive, limits: ArchiveLimits) -> Result<()> {
    let mut tail = archive.into_inner();
    let mut padding = 0usize;
    let mut buffer = vec![0u8; 16384];
    loop {
        let count = tail.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        ensure!(
            buffer[..count].iter().all(|byte| *byte == 0),
            "content after USTAR end marker"
        );
        padding = padding.checked_add(count).context("tar padding overflow")?;
        ensure!(padding <= limits.padding, "archive padding budget exceeded");
    }
    ensure!(
        padding >= 512 && padding.is_multiple_of(512),
        "missing/invalid USTAR end padding"
    );
    Ok(())
}

/// A strict, hash-checked archive materialized only in a private temporary tree.
/// Origin authentication is supplied by the fresh exact-run downloader below.
pub(super) struct VerifiedBundle {
    tree: TempDir,
    manifest: ArtifactManifest,
    hashes: BTreeMap<String, String>,
}

/// Uploaded immutable inputs for one uniquely created protected transaction.
pub(super) struct StagedProvider {
    remote: String,
    local: TempDir,
    sha: String,
    run: String,
    hashes: BTreeMap<String, String>,
}

/// Installation/identity health is distinct from hardware audio acceptance.
#[derive(Debug, PartialEq, Eq)]
pub(super) enum ProviderInstallOutcome {
    QualifiedReady,
    InstalledQualificationPending,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ArtifactManifest {
    schema_version: u32,
    repo_sha: String,
    ci_run_id: String,
    binaries: Vec<FileRecord>,
    provider_manifest_sha256: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct FileRecord {
    file: String,
    sha256: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PackageRecord {
    file: String,
    sha256: String,
    name: String,
    version: String,
    architecture: String,
}
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProviderManifest {
    schema_version: u32,
    repo_sha: String,
    ci_run_id: String,
    source_version: String,
    package_version: String,
    architecture: String,
    source_lock_sha256: String,
    patch_series_sha256: String,
    profile_sha256: String,
    daemon_sha256: String,
    packages: Vec<PackageRecord>,
    source_files: Vec<FileRecord>,
    reports: Vec<FileRecord>,
}

// serde_json::Value normally accepts duplicate object keys. Reject them at every
// depth before deserializing the exact shared schema or examining profile data.
struct UniqueJson(Value);
impl<'de> Deserialize<'de> for UniqueJson {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        struct JsonVisitor;
        impl<'de> Visitor<'de> for JsonVisitor {
            type Value = UniqueJson;
            fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                formatter.write_str("JSON without duplicate keys")
            }
            fn visit_map<A: MapAccess<'de>>(
                self,
                mut map: A,
            ) -> std::result::Result<Self::Value, A::Error> {
                let mut values = serde_json::Map::new();
                while let Some((key, value)) = map.next_entry::<String, UniqueJson>()? {
                    if values.insert(key, value.0).is_some() {
                        return Err(de::Error::custom("duplicate JSON key"));
                    }
                }
                Ok(UniqueJson(Value::Object(values)))
            }
            fn visit_seq<A: SeqAccess<'de>>(
                self,
                mut sequence: A,
            ) -> std::result::Result<Self::Value, A::Error> {
                let mut values = Vec::new();
                while let Some(value) = sequence.next_element::<UniqueJson>()? {
                    values.push(value.0);
                }
                Ok(UniqueJson(Value::Array(values)))
            }
            fn visit_str<E: de::Error>(self, value: &str) -> std::result::Result<Self::Value, E> {
                Ok(UniqueJson(value.into()))
            }
            fn visit_bool<E: de::Error>(self, value: bool) -> std::result::Result<Self::Value, E> {
                Ok(UniqueJson(value.into()))
            }
            fn visit_i64<E: de::Error>(self, value: i64) -> std::result::Result<Self::Value, E> {
                Ok(UniqueJson(value.into()))
            }
            fn visit_u64<E: de::Error>(self, value: u64) -> std::result::Result<Self::Value, E> {
                Ok(UniqueJson(value.into()))
            }
            fn visit_f64<E: de::Error>(self, value: f64) -> std::result::Result<Self::Value, E> {
                serde_json::Number::from_f64(value)
                    .map(|number| UniqueJson(Value::Number(number)))
                    .ok_or_else(|| de::Error::custom("nonfinite JSON number"))
            }
            fn visit_unit<E: de::Error>(self) -> std::result::Result<Self::Value, E> {
                Ok(UniqueJson(Value::Null))
            }
        }
        deserializer.deserialize_any(JsonVisitor)
    }
}
fn json(bytes: &[u8]) -> Result<Value> {
    Ok(serde_json::from_slice::<UniqueJson>(bytes)?.0)
}
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
fn relative(value: &str) -> Result<()> {
    ensure!(
        !value.is_empty()
            && !value.contains(['\\', ':'])
            && !value.chars().any(char::is_control)
            && value
                .split('/')
                .all(|part| !matches!(part, "" | "." | "..")),
        "noncanonical bundle path"
    );
    Ok(())
}
fn regular(path: &Path) -> Result<()> {
    for parent in path.ancestors() {
        let metadata = fs::symlink_metadata(parent)?;
        ensure!(!metadata.file_type().is_symlink(), "symlink in input path");
        ensure!(
            if parent == path {
                metadata.is_file()
            } else {
                metadata.is_dir()
            },
            "non-regular input"
        );
    }
    Ok(())
}
fn digest_reader(reader: &mut impl Read, mut output: Option<&mut File>) -> Result<String> {
    let mut digest = Sha256::new();
    let mut buffer = vec![0u8; 65536];
    loop {
        let count = reader.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
        if let Some(target) = output.as_deref_mut() {
            target.write_all(&buffer[..count])?;
        }
    }
    Ok(format!("{:x}", digest.finalize()))
}
fn header_text(field: &[u8]) -> Result<&str> {
    let end = field
        .iter()
        .position(|byte| *byte == 0)
        .unwrap_or(field.len());
    ensure!(
        field[end..].iter().all(|byte| *byte == 0),
        "nonzero USTAR name padding"
    );
    Ok(std::str::from_utf8(&field[..end])?)
}
fn raw_name(header: &tar::Header) -> Result<(String, bool)> {
    ensure!(
        header.as_ustar().is_some(),
        "only raw USTAR headers are accepted"
    );
    let bytes = header.as_bytes();
    let directory = bytes[156] == b'5';
    ensure!(
        directory || matches!(bytes[156], b'0' | 0),
        "hidden/unsupported USTAR header"
    );
    ensure!(header.mode()? & 0o7000 == 0, "special bundle permissions");
    let leaf = header_text(&bytes[..100])?;
    let prefix = header_text(&bytes[345..500])?;
    let full = if prefix.is_empty() {
        leaf.to_string()
    } else {
        format!("{prefix}/{leaf}")
    };
    let name = if directory {
        full.strip_suffix('/').unwrap_or(&full)
    } else {
        &full
    };
    relative(name)?;
    ensure!(!directory || header.size()? == 0, "directory with payload");
    Ok((name.to_string(), directory))
}

fn profile_validate(
    profile: &Value,
    manifest: &ProviderManifest,
    hashes: &BTreeMap<String, String>,
) -> Result<()> {
    let mut identity = profile.clone();
    let object = identity.as_object_mut().context("profile object")?;
    let qualification = object
        .remove("qualification")
        .context("profile qualification")?;
    let evidence = object.remove("evidence").context("profile evidence")?;
    let mut pinned = json(include_bytes!(
        "../../../../../deploy/providers/modemmanager/profile.json"
    ))?;
    pinned
        .as_object_mut()
        .context("pinned profile")?
        .remove("qualification");
    pinned
        .as_object_mut()
        .context("pinned profile")?
        .remove("evidence");
    ensure!(
        identity == pinned,
        "unknown provider profile or modem/format contract"
    );
    let records = evidence.as_array().context("profile evidence array")?;
    let mut actual = BTreeSet::new();
    if qualification == "qualification_pending" {
        ensure!(records.is_empty(), "pending profile has evidence");
    } else {
        ensure!(
            qualification == "qualified" && records.len() == 2,
            "incomplete provider qualification"
        );
        let mut packages = manifest.packages.clone();
        packages.sort_by(|left, right| left.name.cmp(&right.name));
        let mut sources: Vec<_> = manifest
            .source_files
            .iter()
            .filter(|row| !row.file.starts_with("source/qualification/"))
            .cloned()
            .collect();
        sources.sort_by(|left, right| left.file.cmp(&right.file));
        let inputs = serde_json::json!({"source_version":manifest.source_version,"package_version":manifest.package_version,
            "architecture":manifest.architecture,"source_lock_sha256":manifest.source_lock_sha256,
            "patch_series_sha256":manifest.patch_series_sha256,"daemon_sha256":manifest.daemon_sha256,
            "packages":packages,"source_files":sources});
        // serde_json's default object map sorts keys; nested records use the
        // same sorted Value conversion, matching the shared compact UTF-8 vector.
        let input_hash = hash(&serde_json::to_vec(&inputs)?);
        let mut kinds = BTreeSet::new();
        for record in records {
            let keys: BTreeSet<_> = record
                .as_object()
                .context("evidence object")?
                .keys()
                .map(String::as_str)
                .collect();
            ensure!(
                keys == BTreeSet::from([
                    "kind",
                    "path",
                    "sha256",
                    "modem",
                    "provider_inputs_sha256"
                ]),
                "unknown evidence fields"
            );
            let kind = record["kind"].as_str().context("evidence kind")?;
            let path = record["path"].as_str().context("evidence path")?;
            relative(path)?;
            ensure!(
                matches!(kind, "framing" | "lifecycle")
                    && kinds.insert(kind)
                    && path.starts_with("source/qualification/")
                    && actual.insert(path)
                    && record["modem"] == profile["modem"]
                    && record["provider_inputs_sha256"] == input_hash,
                "evidence identity/input mismatch"
            );
            ensure!(
                hashes.get(&format!("{PROVIDER}{path}")).map(String::as_str)
                    == record["sha256"].as_str(),
                "evidence byte mismatch"
            );
        }
    }
    let listed: BTreeSet<_> = manifest
        .source_files
        .iter()
        .filter(|row| row.file.starts_with("source/qualification/"))
        .map(|row| row.file.as_str())
        .collect();
    ensure!(
        actual == listed,
        "unreferenced/missing qualification source"
    );
    Ok(())
}

fn verify_records(
    root: &ArtifactManifest,
    provider: &ProviderManifest,
    files: &BTreeMap<String, String>,
    profile: &Value,
) -> Result<()> {
    ensure!(
        provider.schema_version == 1
            && provider.repo_sha == root.repo_sha
            && provider.ci_run_id == root.ci_run_id
            && provider.source_version == "1.24.0-1+deb13u1"
            && provider.package_version == "1.24.0-1+deb13u1+yoyopod1"
            && provider.architecture == "arm64",
        "provider identity mismatch"
    );
    let mut expected = BTreeMap::from([
        (
            "manifest.json".to_string(),
            files.get("manifest.json").context("root manifest")?.clone(),
        ),
        (
            format!("{PROVIDER}manifest.json"),
            root.provider_manifest_sha256.clone(),
        ),
        (
            format!("{PROVIDER}profile.json"),
            provider.profile_sha256.clone(),
        ),
    ]);
    ensure!(
        root.binaries.len() == BINARIES.len(),
        "missing/extra binary"
    );
    for (row, name) in root.binaries.iter().zip(BINARIES) {
        ensure!(row.file == name, "binary order/path mismatch");
        expected.insert(name.to_string(), row.sha256.clone());
    }
    ensure!(
        !provider.packages.is_empty()
            && !provider.source_files.is_empty()
            && !provider.reports.is_empty(),
        "incomplete provider payload"
    );
    let mut names = BTreeSet::new();
    for row in &provider.packages {
        ensure!(
            row.file.starts_with("packages/")
                && row.name.len() >= 2
                && names.insert(row.name.as_str())
                && row
                    .name
                    .bytes()
                    .next()
                    .is_some_and(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
                && row.name.bytes().all(|byte| byte.is_ascii_lowercase()
                    || byte.is_ascii_digit()
                    || b"+.-".contains(&byte))
                && !row.version.is_empty()
                && matches!(row.architecture.as_str(), "arm64" | "all"),
            "invalid package row"
        );
        ensure!(
            expected
                .insert(format!("{PROVIDER}{}", row.file), row.sha256.clone())
                .is_none(),
            "duplicate provider row"
        );
    }
    for name in ["modemmanager", "libmm-glib0"] {
        ensure!(
            provider.packages.iter().any(|row| row.name == name
                && row.version == provider.package_version
                && row.architecture == "arm64"),
            "missing runtime package"
        );
    }
    for (rows, prefix) in [
        (&provider.source_files, "source/"),
        (&provider.reports, "reports/"),
    ] {
        for row in rows {
            ensure!(row.file.starts_with(prefix), "wrong provider section path");
            ensure!(
                expected
                    .insert(format!("{PROVIDER}{}", row.file), row.sha256.clone())
                    .is_none(),
                "duplicate provider row"
            );
        }
    }
    for (name, digest) in &expected {
        relative(name)?;
        ensure!(hex(digest, 64), "invalid file digest");
    }
    ensure!(&expected == files, "bundle membership/hash mismatch");
    for (name, digest) in [
        ("source/source-lock.json", &provider.source_lock_sha256),
        ("source/patches/series", &provider.patch_series_sha256),
    ] {
        ensure!(
            hex(digest, 64) && files.get(&format!("{PROVIDER}{name}")) == Some(digest),
            "source input hash mismatch"
        );
    }
    ensure!(hex(&provider.daemon_sha256, 64), "invalid daemon hash");
    profile_validate(profile, provider, files)
}

/// Verify the selected artifact's complete raw tar/schema/hash contract before
/// materializing any selected file. This never equates operator HEAD to its SHA.
pub(super) fn verify_bundle(path: &Path, sha: &str, run: &str) -> Result<VerifiedBundle> {
    verify_bundle_with_limits(path, sha, run, ARCHIVE_LIMITS)
}
fn verify_bundle_with_limits(
    path: &Path,
    sha: &str,
    run: &str,
    limits: ArchiveLimits,
) -> Result<VerifiedBundle> {
    ensure!(
        hex(sha, 40) && !run.is_empty() && run.bytes().all(|byte| byte.is_ascii_digit()),
        "invalid selected artifact identity"
    );
    let path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()?.join(path)
    };
    regular(&path)?;
    let path = path.canonicalize()?;
    let mut archive = open_archive(&path, limits)?;
    let mut hashes = BTreeMap::new();
    let mut seen = BTreeSet::new();
    let mut dirs = BTreeSet::new();
    let mut json_files = BTreeMap::new();
    for (index, entry) in archive.entries()?.raw(true).enumerate() {
        let mut entry = entry?;
        check_member(entry.header(), index, limits)?;
        let (name, directory) = raw_name(entry.header())?;
        ensure!(seen.insert(name.clone()), "duplicate archive member");
        if directory {
            dirs.insert(name);
            continue;
        }
        let digest = if matches!(
            name.as_str(),
            "manifest.json"
                | "providers/modemmanager/manifest.json"
                | "providers/modemmanager/profile.json"
        ) {
            ensure!(
                entry.header().size()? <= limits.json,
                "archive JSON budget exceeded"
            );
            let mut bytes = Vec::new();
            entry.read_to_end(&mut bytes)?;
            let digest = hash(&bytes);
            json_files.insert(name.clone(), bytes);
            digest
        } else {
            digest_reader(&mut entry, None)?
        };
        hashes.insert(name, digest);
    }
    finish_archive(archive, limits)?;
    let root: ArtifactManifest = serde_json::from_value(json(
        json_files
            .get("manifest.json")
            .context("missing artifact manifest")?,
    )?)?;
    ensure!(
        root.schema_version == 1 && root.repo_sha == sha && root.ci_run_id == run,
        "artifact SHA/run/schema mismatch"
    );
    let provider: ProviderManifest = serde_json::from_value(json(
        json_files
            .get("providers/modemmanager/manifest.json")
            .context("missing provider manifest")?,
    )?)?;
    let profile = json(
        json_files
            .get("providers/modemmanager/profile.json")
            .context("missing profile")?,
    )?;
    verify_records(&root, &provider, &hashes, &profile)?;
    let allowed_dirs: BTreeSet<_> = hashes
        .keys()
        .flat_map(|name| {
            let mut prefixes = Vec::new();
            let mut current = String::new();
            for part in name.split('/').take(name.split('/').count() - 1) {
                if !current.is_empty() {
                    current.push('/');
                }
                current.push_str(part);
                prefixes.push(current.clone());
            }
            prefixes
        })
        .collect();
    ensure!(dirs.is_subset(&allowed_dirs), "extra archive directory");
    let tree = tempfile::tempdir()?;
    let mut archive = open_archive(&path, limits)?;
    for (index, entry) in archive.entries()?.raw(true).enumerate() {
        let mut entry = entry?;
        check_member(entry.header(), index, limits)?;
        let (name, directory) = raw_name(entry.header())?;
        if directory {
            continue;
        }
        let destination = tree.path().join(&name);
        fs::create_dir_all(destination.parent().context("file parent")?)?;
        let mut target = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&destination)?;
        ensure!(
            hashes.get(&name) == Some(&digest_reader(&mut entry, Some(&mut target))?),
            "archive changed during verification"
        );
    }
    finish_archive(archive, limits)?;
    Ok(VerifiedBundle {
        tree,
        manifest: root,
        hashes,
    })
}

pub(super) fn fresh_bundle(run: &str, sha: &str) -> Result<VerifiedBundle> {
    let download = tempfile::tempdir()?;
    let name = format!("yoyopod-rust-device-arm64-{sha}");
    // Never authenticate a cache using its name or self-asserted manifest.
    // gh obtains these fresh bytes from the selected successful exact run.
    deploy::download_artifact(run, &name, download.path())?;
    verify_bundle(&download.path().join(format!("{name}.tar.gz")), sha, run)
}

fn scp(ctx: &TargetContext, source: &Path, destination: &str, recursive: bool) -> Result<()> {
    let mut command = Command::new("scp");
    if recursive {
        command.arg("-r");
    }
    let status = command
        .arg(source)
        .arg(format!(
            "{}:{}",
            ctx.conn.ssh_target(),
            shell_quote(destination)
        ))
        .status()?;
    ensure!(status.success(), "provider stage upload failed");
    Ok(())
}

/// Upload checked inputs only. The locked transaction captures/simulates the
/// complete prior closure before any service or checkout mutation.
pub(super) fn stage_provider(
    ctx: &TargetContext,
    bundle: &VerifiedBundle,
) -> Result<StagedProvider> {
    ensure!(
        !ctx.dry_run && Path::new(&ctx.conn.project_dir).is_absolute(),
        "invalid provider stage target"
    );
    let output = run_remote_capture(
        &ctx.conn,
        "umask 077; mktemp -d /tmp/yoyopod-provider.XXXXXXXXXXXX",
        RemoteWorkdir::None,
    )?;
    ensure!(output.success(), "cannot create private upload stage");
    let remote = output.stdout.trim().to_string();
    ensure!(
        remote.starts_with("/tmp/yoyopod-provider.")
            && remote
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"/.-".contains(&byte)),
        "invalid remote stage path"
    );
    scp(
        ctx,
        bundle.tree.path(),
        &format!("{remote}/candidate"),
        true,
    )?;
    let local = tempfile::tempdir()?;
    let repository = local.path().join("repository.bundle");
    let status = Command::new("git")
        .current_dir(current_repo_root()?)
        .args(["bundle", "create"])
        .arg(&repository)
        .arg(format!("origin/{}", ctx.conn.branch))
        .status()?;
    ensure!(
        status.success(),
        "cannot stage selected committed repository"
    );
    fs::write(local.path().join("transaction.sh"), TRANSACTION)?;
    fs::write(local.path().join("udev.rules"), UDEV_RULE)?;
    Ok(StagedProvider {
        remote,
        local,
        sha: bundle.manifest.repo_sha.clone(),
        run: bundle.manifest.ci_run_id.clone(),
        hashes: bundle
            .hashes
            .iter()
            .map(|(name, digest)| (format!("candidate/{name}"), digest.clone()))
            .collect(),
    })
}

/// Execute only the embedded, hash-bound transaction in its protected attempt
/// directory. Both outcomes describe expected eligibility, never audio success.
pub(super) fn apply_provider(
    ctx: &TargetContext,
    staged: &StagedProvider,
    lane: &LanePaths,
    pi: &PiPaths,
) -> Result<ProviderInstallOutcome> {
    ensure!(
        ctx.conn.project_dir == lane.dev_checkout && pi.project_dir == lane.dev_checkout,
        "explicit provider maintenance requires the selected dev checkout"
    );
    for unit in [&lane.dev_service, &lane.prod_service] {
        ensure!(
            unit.ends_with(".service")
                && unit
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || b"_.@-".contains(&byte)),
            "invalid service unit"
        );
    }
    let control = serde_json::json!({"schema_version":1,"repo_sha":staged.sha,"ci_run_id":staged.run,
        "dev_checkout":lane.dev_checkout,"branch":ctx.conn.branch,"pid_file":pi.pid_file,
        "log_file":pi.log_file,"startup_marker":pi.startup_marker});
    fs::write(
        staged.local.path().join("control.json"),
        serde_json::to_vec(&control)?,
    )?;
    fs::write(
        staged.local.path().join("native-verify.sh"),
        ops::build_startup_verification(pi, 20),
    )?;
    let mut hashes = staged.hashes.clone();
    for name in [
        "repository.bundle",
        "transaction.sh",
        "udev.rules",
        "control.json",
        "native-verify.sh",
    ] {
        let path = staged.local.path().join(name);
        hashes.insert(
            name.to_string(),
            digest_reader(&mut File::open(&path)?, None)?,
        );
        scp(ctx, &path, &format!("{}/{name}", staged.remote), false)?;
    }
    let mut listing = String::new();
    for (name, digest) in &hashes {
        listing.push_str(digest);
        listing.push_str("  ");
        listing.push_str(name);
        listing.push('\n');
    }
    fs::write(staged.local.path().join("inputs.sha256"), &listing)?;
    scp(
        ctx,
        &staged.local.path().join("inputs.sha256"),
        &format!("{}/inputs.sha256", staged.remote),
        false,
    )?;
    // Copy the script first, verify its compiled hash as root, then let that
    // trusted script protect/copy all other stage input before sourcing anything.
    let command = format!("sudo -n bash -c {} -- {} {} {} {} {}",
        shell_quote("set -euo pipefail; test -f \"$1/transaction.sh\" && test ! -L \"$1/transaction.sh\"; script=$(mktemp /run/yoyopod-provider.XXXXXXXXXXXX); trap 'rm -f -- \"$script\"' EXIT; timeout --signal=TERM --kill-after=2s 10s install -o root -g root -m 0700 -- \"$1/transaction.sh\" \"$script\"; printf '%s  %s\\n' \"$2\" \"$script\" | sha256sum -c --strict >&2; YOYOPOD_STAGE_INPUTS_SHA256=\"$5\" bash \"$script\" \"$1\" \"$3\" \"$4\""),
        shell_quote(&staged.remote), shell_quote(&hash(TRANSACTION.as_bytes())), shell_quote(&lane.dev_service),
        shell_quote(&lane.prod_service), shell_quote(&hash(listing.as_bytes())));
    let output = run_remote_capture(&ctx.conn, &command, RemoteWorkdir::None)?;
    eprint!("{}", output.stderr);
    ensure!(output.success(), "provider transaction failed; retained protected stage/recovery record identifies rollback or recovery required");
    let last = output
        .stdout
        .lines()
        .last()
        .context("missing root transaction outcome")?;
    let outcome = json(last.as_bytes())?;
    match outcome["outcome"].as_str() {
        Some("qualified_ready") => Ok(ProviderInstallOutcome::QualifiedReady),
        Some("installed_qualification_pending") => {
            Ok(ProviderInstallOutcome::InstalledQualificationPending)
        }
        _ => bail!("unknown successful provider transaction outcome"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::write::GzEncoder;
    use flate2::Compression;
    use std::io::{self, Cursor};

    const SHA: &str = "1111111111111111111111111111111111111111";
    const RUN: &str = "12345";

    // Hermetic fake package/source bytes test the archive contract only. Real
    // dpkg control/daemon checks remain mandatory during protected staging.
    fn fixture() -> BTreeMap<String, Vec<u8>> {
        let mut files = BTreeMap::new();
        for name in BINARIES {
            files.insert(
                name.to_string(),
                format!("synthetic Rust binary {name}").into_bytes(),
            );
        }
        let mut packages = Vec::new();
        for name in ["modemmanager", "libmm-glib0"] {
            let path = format!("packages/{name}.deb");
            let bytes = format!("synthetic package, never install: {name}").into_bytes();
            packages.push(serde_json::json!({"file":path,"sha256":hash(&bytes),"name":name,"version":"1.24.0-1+deb13u1+yoyopod1","architecture":"arm64"}));
            files.insert(format!("{PROVIDER}{path}"), bytes);
        }
        let mut source = Vec::new();
        for (name, bytes) in [
            (
                "source/source-lock.json",
                b"synthetic signed-lock bytes".as_slice(),
            ),
            ("source/patches/series", b"synthetic.patch\n".as_slice()),
            (
                "source/licenses/example.copyright",
                b"synthetic license".as_slice(),
            ),
            (
                "source/dependencies/example.tar.xz",
                b"synthetic source".as_slice(),
            ),
        ] {
            source.push(serde_json::json!({"file":name,"sha256":hash(bytes)}));
            files.insert(format!("{PROVIDER}{name}"), bytes.to_vec());
        }
        let profile =
            include_bytes!("../../../../../deploy/providers/modemmanager/profile.json").to_vec();
        files.insert(format!("{PROVIDER}profile.json"), profile.clone());
        files.insert(
            format!("{PROVIDER}reports/test.log"),
            b"synthetic test evidence".to_vec(),
        );
        let provider = serde_json::json!({"schema_version":1,"repo_sha":SHA,"ci_run_id":RUN,
            "source_version":"1.24.0-1+deb13u1","package_version":"1.24.0-1+deb13u1+yoyopod1","architecture":"arm64",
            "source_lock_sha256":hash(&files[&format!("{PROVIDER}source/source-lock.json")]),
            "patch_series_sha256":hash(&files[&format!("{PROVIDER}source/patches/series")]),
            "profile_sha256":hash(&profile),"daemon_sha256":"a".repeat(64),"packages":packages,"source_files":source,
            "reports":[{"file":"reports/test.log","sha256":hash(&files[&format!("{PROVIDER}reports/test.log")])}]});
        let provider_bytes = serde_json::to_vec(&provider).unwrap();
        let root = serde_json::json!({"schema_version":1,"repo_sha":SHA,"ci_run_id":RUN,
            "provider_manifest_sha256":hash(&provider_bytes),
            "binaries":BINARIES.iter().map(|name|serde_json::json!({"file":name,"sha256":hash(&files[*name])})).collect::<Vec<_>>()});
        files.insert(format!("{PROVIDER}manifest.json"), provider_bytes);
        files.insert(
            "manifest.json".to_string(),
            serde_json::to_vec(&root).unwrap(),
        );
        files
    }

    fn raw_header(name: &str, directory: bool, size: usize, prefix_split: bool) -> tar::Header {
        let mut header = tar::Header::new_ustar();
        header.set_mode(if directory { 0o755 } else { 0o644 });
        header.set_size(u64::try_from(size).unwrap());
        header.set_entry_type(if directory {
            tar::EntryType::Directory
        } else {
            tar::EntryType::Regular
        });
        if prefix_split {
            let (prefix, leaf) = name.rsplit_once('/').unwrap();
            header.as_mut_bytes()[..leaf.len()].copy_from_slice(leaf.as_bytes());
            header.as_mut_bytes()[345..345 + prefix.len()].copy_from_slice(prefix.as_bytes());
        } else {
            assert!(name.len() <= 100);
            header.as_mut_bytes()[..name.len()].copy_from_slice(name.as_bytes());
        }
        header.set_cksum();
        header
    }

    fn archive(files: &BTreeMap<String, Vec<u8>>, path: &Path, mutation: &str) {
        let gzip = GzEncoder::new(File::create(path).unwrap(), Compression::fast());
        let mut archive = tar::Builder::new(gzip);
        let mut dirs = BTreeSet::new();
        for name in files.keys() {
            let mut parent = name.as_str();
            while let Some((next, _)) = parent.rsplit_once('/') {
                dirs.insert(next);
                parent = next;
            }
        }
        for name in dirs {
            let raw = if name == "device" {
                match mutation {
                    "double-slash" => "device//",
                    "triple-slash" => "device///",
                    _ => "device/",
                }
            } else {
                name
            };
            let mut header = raw_header(raw, true, 0, false);
            if name == "device" && mutation == "regular-directory" {
                header.as_mut_bytes()[156] = 0;
                header.set_cksum();
            }
            archive.append(&header, io::empty()).unwrap();
        }
        for (name, bytes) in files {
            if name == BINARIES[5] && matches!(mutation, "gnu-longname" | "pax") {
                let data = if mutation == "gnu-longname" {
                    format!("{name}\0").into_bytes()
                } else {
                    Vec::new()
                };
                let mut header = raw_header("hidden", false, data.len(), false);
                header.as_mut_bytes()[156] = if mutation == "pax" { b'x' } else { b'L' };
                header.set_cksum();
                archive.append(&header, Cursor::new(data)).unwrap();
            }
            let mut header = raw_header(
                name,
                false,
                bytes.len(),
                mutation == "prefix" && name == BINARIES[5],
            );
            if name == BINARIES[5] && mutation == "link" {
                header.as_mut_bytes()[156] = b'2';
                header.set_cksum();
            }
            archive.append(&header, Cursor::new(bytes)).unwrap();
            if name == BINARIES[5] && mutation == "duplicate" {
                archive.append(&header, Cursor::new(bytes)).unwrap();
            }
        }
        archive.into_inner().unwrap().finish().unwrap();
    }

    #[test]
    fn provider_archive_accepts_pending_and_both_raw_ustar_controls() {
        let directory = tempfile::tempdir().unwrap();
        for control in ["normal", "prefix"] {
            let path = directory.path().join(format!("{control}.tar.gz"));
            archive(&fixture(), &path, control);
            let bundle = verify_bundle(&path, SHA, RUN).unwrap();
            assert_eq!(bundle.manifest.repo_sha, SHA);
            assert_eq!(bundle.hashes.len(), fixture().len());
            assert_eq!(
                fs::read(bundle.tree.path().join(BINARIES[5])).unwrap(),
                fixture()[BINARIES[5]]
            );
            assert!(verify_bundle(&path, &"2".repeat(40), RUN).is_err());
            assert!(verify_bundle(&path, SHA, "999").is_err());
        }
    }
    #[test]
    fn provider_archive_rejects_hidden_headers_aliases_and_changed_bytes() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("mutation.tar.gz");
        for mutation in [
            "double-slash",
            "triple-slash",
            "regular-directory",
            "gnu-longname",
            "pax",
            "link",
            "duplicate",
        ] {
            archive(&fixture(), &path, mutation);
            assert!(
                verify_bundle(&path, SHA, RUN).is_err(),
                "accepted {mutation}"
            );
        }
        for removed in [
            "providers/modemmanager/source/licenses/example.copyright",
            "providers/modemmanager/source/dependencies/example.tar.xz",
        ] {
            let mut files = fixture();
            files.remove(removed);
            archive(&files, &path, "normal");
            assert!(verify_bundle(&path, SHA, RUN).is_err());
        }
        let mut files = fixture();
        files.insert(BINARIES[5].to_string(), b"changed after manifest".to_vec());
        archive(&files, &path, "normal");
        assert!(verify_bundle(&path, SHA, RUN).is_err());
        files = fixture();
        files.insert("../outside".to_string(), b"traversal".to_vec());
        archive(&files, &path, "normal");
        assert!(verify_bundle(&path, SHA, RUN).is_err());
        files = fixture();
        files.insert("extra.txt".to_string(), b"extra".to_vec());
        archive(&files, &path, "normal");
        assert!(verify_bundle(&path, SHA, RUN).is_err());
        archive(&fixture(), &path, "normal");
        let file = OpenOptions::new().append(true).open(&path).unwrap();
        let mut extra = GzEncoder::new(file, Compression::fast());
        extra.write_all(b"hidden second gzip payload").unwrap();
        extra.finish().unwrap();
        assert!(verify_bundle(&path, SHA, RUN).is_err());
    }
    #[test]
    fn provider_archive_rejects_duplicate_json_and_incomplete_qualification() {
        assert!(json(br#"{"outer":{"key":1,"key":2}}"#).is_err());
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("profile.tar.gz");
        let mut files = fixture();
        let profile_path = format!("{PROVIDER}profile.json");
        let mut profile = json(&files[&profile_path]).unwrap();
        profile["qualification"] = "qualified".into();
        files.insert(profile_path, serde_json::to_vec(&profile).unwrap());
        let inner_path = format!("{PROVIDER}manifest.json");
        let mut inner = json(&files[&inner_path]).unwrap();
        inner["profile_sha256"] = hash(&files[&format!("{PROVIDER}profile.json")]).into();
        files.insert(inner_path.clone(), serde_json::to_vec(&inner).unwrap());
        let mut root = json(&files["manifest.json"]).unwrap();
        root["provider_manifest_sha256"] = hash(&files[&inner_path]).into();
        files.insert(
            "manifest.json".to_string(),
            serde_json::to_vec(&root).unwrap(),
        );
        archive(&files, &path, "normal");
        assert!(verify_bundle(&path, SHA, RUN).is_err());
    }
    #[test]
    fn provider_archive_enforces_resource_budgets_before_payload_allocation() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("budget.tar.gz");
        archive(&fixture(), &path, "normal");
        verify_bundle_with_limits(&path, SHA, RUN, ARCHIVE_LIMITS).unwrap();
        for (limits, expected) in [
            (
                ArchiveLimits {
                    compressed: 1,
                    ..ARCHIVE_LIMITS
                },
                "compressed archive budget",
            ),
            (
                ArchiveLimits {
                    expanded: 512,
                    ..ARCHIVE_LIMITS
                },
                "expanded archive budget",
            ),
            (
                ArchiveLimits {
                    member: 1,
                    ..ARCHIVE_LIMITS
                },
                "archive member budget",
            ),
            (
                ArchiveLimits {
                    json: 1,
                    ..ARCHIVE_LIMITS
                },
                "archive JSON budget",
            ),
            (
                ArchiveLimits {
                    members: 1,
                    ..ARCHIVE_LIMITS
                },
                "member count budget",
            ),
            (
                ArchiveLimits {
                    padding: 0,
                    ..ARCHIVE_LIMITS
                },
                "padding budget",
            ),
        ] {
            let error = verify_bundle_with_limits(&path, SHA, RUN, limits)
                .err()
                .unwrap();
            assert!(format!("{error:#}").contains(expected), "{error:#}");
        }
    }
    #[test]
    #[ignore = "coordinator invokes explicitly with authenticated Task6 artifact path/SHA/run"]
    fn provider_real_selected_artifact() {
        let path = std::env::var_os("YOYOPOD_TEST_PROVIDER_TAR").expect("actual tar path required");
        let sha = std::env::var("YOYOPOD_TEST_PROVIDER_SHA").expect("selected exact SHA required");
        let run = std::env::var("YOYOPOD_TEST_PROVIDER_RUN").expect("selected exact run required");
        let verified = verify_bundle(Path::new(&path), &sha, &run).unwrap();
        assert_eq!(verified.manifest.repo_sha, sha);
        assert_eq!(verified.manifest.ci_run_id, run);
        assert_eq!(verified.hashes.len(), 372);
    }
}
