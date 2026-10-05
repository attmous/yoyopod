#!/usr/bin/env bash
# Acquisition runs only in the ARM64 child of the official Debian image.
set -euo pipefail
[[ $# == 1 ]] || { echo 'usage: resolve-lock.sh OUTPUT_JSON' >&2; exit 1; }
[[ $(dpkg --print-architecture) == arm64 ]] || { echo 'requires native Debian ARM64' >&2; exit 1; }
[[ ${MM_IMAGE:-} =~ ^docker.io/library/debian@sha256:[0-9a-f]{64}$ ]] || { echo 'missing resolved ARM64 image digest' >&2; exit 1; }
: "${MM_IMAGE_INDEX:?official image index required}" "${MM_IMAGE_MANIFEST:?official child manifest required}"
root=$(cd "$(dirname "$0")/.." && pwd)
output=$(realpath -m "$1")
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
snapshot=20261006T000000Z
if [[ "$snapshot" > $(date -u +%Y%m%dT%H%M%SZ) ]]; then snapshot=$(date -u -d yesterday +%Y%m%dT000000Z); fi
base="https://snapshot.debian.org/archive/debian/$snapshot"
# apt's trusted image keyring authenticates bootstrap tools from this fixed
# snapshot. HTTP is used only until ca-certificates is available; apt signature
# and index hash validation stay enabled, including during this bootstrap.
rm -f /etc/apt/sources.list.d/debian.sources
printf 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/%s trixie main\ndeb-src [check-valid-until=no] http://snapshot.debian.org/archive/debian/%s trixie main\n' "$snapshot" "$snapshot" > /etc/apt/sources.list
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates
printf 'bootstrap_snapshot=%s\nbootstrap_archive_keyring_sha256=%s\ncertificate_bundle_sha256=%s\n' \
    "$snapshot" "$(sha256sum /usr/share/keyrings/debian-archive-keyring.gpg | cut -d ' ' -f 1)" \
    "$(sha256sum /etc/ssl/certs/ca-certificates.crt | cut -d ' ' -f 1)" > "$work/bootstrap.txt"
dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\n' >> "$work/bootstrap.txt"
# From here all downloads use HTTPS with normal certificate validation.
sed -i 's|http://snapshot|https://snapshot|' /etc/apt/sources.list
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    curl jq gpgv gnupg devscripts debian-keyring build-essential meson xz-utils
source "$root/build/verify-inputs.sh"
[[ $(hash "$MM_IMAGE_MANIFEST") == "${MM_IMAGE##*@sha256:}" ]] || fail 'official child manifest bytes do not match digest'
jq -e --arg digest "${MM_IMAGE##*@}" '[.manifests[]|select(.platform.os=="linux" and .platform.architecture=="arm64")]|length==1 and .[0].digest==$digest' "$MM_IMAGE_INDEX" >/dev/null || fail 'ARM image index mismatch'
fetch "$base/dists/trixie/InRelease" "$work/InRelease"
actual_uri=$(cat "$work/InRelease.uri")
[[ "$actual_uri" =~ ^https://snapshot.debian.org/file/[0-9a-f]{40}/InRelease$ || "$actual_uri" == "$base/dists/trixie/InRelease" ]] || fail 'unexpected actual snapshot metadata URI'
archive_signer=$(signer /usr/share/keyrings/debian-archive-keyring.gpg "$work/InRelease" "$work/archive-signature.txt" archive)
grep -qx 'Codename: trixie' "$work/InRelease" || fail 'unexpected Debian suite'
for kind in packages sources; do
    if [[ "$kind" == packages ]]; then path=main/binary-arm64/Packages.xz; else path=main/source/Sources.xz; fi
    expected=$(release_hash "$work/InRelease" "$path")
    [[ "$expected" =~ ^[0-9a-f]{64}$ ]] || fail 'missing signed index hash'
    fetch "$base/dists/trixie/$path" "$work/$kind.xz" "$expected"
    xz -dc "$work/$kind.xz" > "$work/$kind.txt"
done
package_index "$work/packages.txt" > "$work/packages.json"
source_index "$work/sources.txt" > "$work/sources.json"
jq -e 'length==3' "$work/sources.json" >/dev/null || fail 'exact source version unavailable in dated snapshot'
mkdir "$work/downloads"
touch "$work/archives.jsonl"
while IFS=$'\t' read -r expected filename; do
    fetch "$base/$filename" "$work/downloads/${filename##*/}" "$expected"
    jq -n --arg name "${filename##*/}" --arg request_uri "$base/$filename" \
        --arg uri "$(cat "$work/downloads/${filename##*/}.uri")" --arg sha256 "$expected" \
        '{name:$name,request_uri:$request_uri,uri:$uri,sha256:$sha256}' >> "$work/archives.jsonl"
done < <(jq -r '.[]|[.sha256,.filename]|@tsv' "$work/sources.json")
jq -s . "$work/archives.jsonl" > "$work/archives.json"
dsc="$work/downloads/modemmanager_1.24.0-1+deb13u1.dsc"
[[ $(hash "$work/downloads/modemmanager_1.24.0.orig.tar.xz") == 63ded4c0f3936bb0db5ae35ef1dfd57c5d5b4dd8a5cdaa7fb2182255218c9168 \
    && $(hash "$work/downloads/modemmanager_1.24.0-1+deb13u1.debian.tar.xz") == 0362e74213576b3f830b344f139407843a6caf6b9ae892c5a085a340da6999f2 ]] || fail 'unexpected required baseline archives'
dsc_signer=$(signer /usr/share/keyrings/debian-keyring.gpg "$dsc" "$work/descriptor-signature.txt")
dscverify --keyring /usr/share/keyrings/debian-keyring.gpg "$dsc"
dpkg-source --no-check -x "$dsc" "$work/source"
# Use the actual exact Debian control file, not dependencies transcribed from a
# different upstream release. apt resolves the complete installed closure.
DEBIAN_FRONTEND=noninteractive apt-get build-dep -y "$work/source"
dpkg-checkbuilddeps "$work/source/debian/control"
dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\n' > "$work/installed.tsv"
jq -Rn '[inputs|split("\t")|{name:(.[0]|split(":")[0]),version:.[1],architecture:.[2]}]' < "$work/installed.tsv" > "$work/installed.json"
jq --slurpfile index "$work/packages.json" '[.[]|. as $installed |
    [$index[0][]|select(.name==$installed.name and .version==$installed.version and .architecture==$installed.architecture)] |
    if length==1 then .[0]|del(.filename) else error("installed package not uniquely available in signed snapshot") end]' \
    "$work/installed.json" > "$work/dependencies.json"
jq -n --arg image "$MM_IMAGE" --arg snapshot "$snapshot" --arg base "$base/" \
    --arg archive_keyring "$(hash /usr/share/keyrings/debian-archive-keyring.gpg)" \
    --arg maintainer_keyring "$(hash /usr/share/keyrings/debian-keyring.gpg)" \
    --arg archive_signer "$archive_signer" --arg dsc_signer "$dsc_signer" \
    --arg release_hash "$(hash "$work/InRelease")" --arg packages_hash "$(hash "$work/packages.xz")" --arg sources_hash "$(hash "$work/sources.xz")" \
    --arg release_uri "$(cat "$work/InRelease.uri")" --arg packages_uri "$(cat "$work/packages.xz.uri")" --arg sources_uri "$(cat "$work/sources.xz.uri")" \
    --arg gcc "$(gcc -dumpfullversion)" --arg meson "$(meson --version)" --arg dpkg "$(dpkg-query -W -f='${Version}' dpkg)" \
    --arg image_manifest_sha256 "$(hash "$MM_IMAGE_MANIFEST")" --arg image_index_sha256 "$(hash "$MM_IMAGE_INDEX")" \
    --argjson epoch "$(dpkg-parsechangelog -l "$work/source/debian/changelog" -S Timestamp)" \
    --slurpfile sources "$work/archives.json" --slurpfile dependencies "$work/dependencies.json" '
    $sources[0] as $archives |
    {schema_version:1,source_version:"1.24.0-1+deb13u1",package_version:"1.24.0-1+deb13u1+yoyopod1",
     architecture:"arm64",image:$image,snapshot:$snapshot,source_date_epoch:$epoch,
     archive_keyring_sha256:$archive_keyring,maintainer_keyring_sha256:$maintainer_keyring,
     signed_metadata:[
       {kind:"release",request_uri:($base+"dists/trixie/InRelease"),uri:$release_uri,sha256:$release_hash,signer_fingerprint:$archive_signer},
       {kind:"packages",request_uri:($base+"dists/trixie/main/binary-arm64/Packages.xz"),uri:$packages_uri,sha256:$packages_hash,signer_fingerprint:$archive_signer},
       {kind:"sources",request_uri:($base+"dists/trixie/main/source/Sources.xz"),uri:$sources_uri,sha256:$sources_hash,signer_fingerprint:$archive_signer},
       ($archives[]|select(.name|endswith(".dsc"))|{kind:"dsc",request_uri,uri,sha256,signer_fingerprint:$dsc_signer})],
     sources:$archives,build_dependencies:$dependencies[0],
     toolchain:{gcc:$gcc,meson:$meson,dpkg:$dpkg,image_manifest_sha256:$image_manifest_sha256,image_index_sha256:$image_index_sha256},patches:[]}
    ' > "$work/lock.json"
validate_schema "$work/lock.json"
validate_request_paths "$work/lock.json" "$base"
mkdir -p "$(dirname "$output")"
cp -- "$work/lock.json" "$output"
# Keep genuine acquisition evidence together with the lock. No arbitrary files
# from the runner host are mounted/passed to the container.
evidence="$(dirname "$output")/acquisition"
mkdir -p "$evidence"
cp "$work/bootstrap.txt" "$work/installed.tsv" "$work/archive-signature.txt" "$work/archive-signature.txt.fingerprints" "$work/descriptor-signature.txt" "$work/InRelease" "$work/InRelease.uri" "$work/packages.xz" "$work/packages.xz.uri" "$work/sources.xz" "$work/sources.xz.uri" "$dsc" "$evidence/"
echo "Resolved verified Debian ARM64 lock: $output"
