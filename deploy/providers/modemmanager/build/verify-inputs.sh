#!/usr/bin/env bash
# Helpers are shared with acquisition; executing this file always validates.
set -euo pipefail

fail() { echo "input verification: $*" >&2; return 1; }
hash() { sha256sum "$1" | cut -d ' ' -f 1; }
fetch() {
    local uri=$1 destination=$2 expected=${3:-} pinned_final=${4:-}
    if [[ -f "$destination" && -n "$expected" ]]; then
        [[ $(hash "$destination") == "$expected" ]] || { fail "cached hash mismatch: $uri"; return 1; }
    fi
    # A URI sidecar cannot authenticate a dated snapshot request. Reissue the
    # original HTTPS request and check its response bytes/effective URI on every
    # validation, including when the pinned bytes already exist in this cache.
    if [[ ! -f "$destination" || -n "$pinned_final" ]]; then
        curl --fail --location --proto '=https' --proto-redir '=https' \
            --retry 3 --connect-timeout 30 --max-time 600 --write-out '%{url_effective}' \
            "$uri" -o "$destination.tmp" > "$destination.uri.tmp" || return 1
        [[ -z "$expected" || $(hash "$destination.tmp") == "$expected" ]] || { fail "response hash mismatch: $uri"; return 1; }
        [[ -z "$pinned_final" || $(cat "$destination.uri.tmp") == "$pinned_final" ]] || { fail "dated request effective URI mismatch: $uri"; return 1; }
        mv -- "$destination.tmp" "$destination" || return 1
        mv -- "$destination.uri.tmp" "$destination.uri" || return 1
        printf '%s' "$uri" > "$destination.request-uri"
    fi
    [[ -z "$expected" || $(hash "$destination") == "$expected" ]] || fail "hash mismatch: $uri"
}
signer() {
    local keyring=$1 input=$2 status=$3 policy=${4:-descriptor}
    gpgv --status-fd 1 --keyring "$keyring" "$input" > "$status" || return 1
    awk '$1 == "[GNUPG:]" && $2 == "VALIDSIG" {print $3}' "$status" | LC_ALL=C sort -u > "$status.fingerprints"
    case "$policy" in
        archive) [[ -s "$status.fingerprints" ]] || { fail "no verified archive signers: $input"; return 1; } ;;
        descriptor) [[ $(wc -l < "$status.fingerprints") == 1 ]] || { fail "expected one verified descriptor signer: $input"; return 1; } ;;
        *) fail 'unknown signature policy'; return 1 ;;
    esac
    # Scalar lock field follows a deterministic policy; the full verified set
    # remains in status.fingerprints and is included in signature evidence.
    head -n 1 "$status.fingerprints"
}
package_index() {
    # Derived only from the Release-hash-verified Packages file.
    awk 'BEGIN {RS=""; FS="\n"; OFS="\t"}
      {delete fields; for(i=1;i<=NF;i++) {p=index($i,": "); if(p) fields[substr($i,1,p-1)]=substr($i,p+2)}
       print fields["Package"],fields["Version"],fields["Architecture"],fields["SHA256"],fields["Filename"]}' "$1" |
      jq -Rn '[inputs | split("\t") | {name:.[0], version:.[1], architecture:.[2], sha256:.[3], filename:.[4]}]'
}
source_index() {
    awk 'BEGIN {RS=""; FS="\n"; OFS="\t"}
      {package=""; version=""; directory=""; checks=0;
       for(i=1;i<=NF;i++) {
         if($i ~ /^Package: /) package=substr($i,10);
         if($i ~ /^Version: /) version=substr($i,10);
         if($i ~ /^Directory: /) directory=substr($i,12);
       }
       if(package=="modemmanager" && version=="1.24.0-1+deb13u1") {
         for(i=1;i<=NF;i++) {
           if($i=="Checksums-Sha256:") {checks=1; continue}
           if(checks && $i !~ /^ /) checks=0;
           if(checks) {split($i,a," "); print a[1],directory "/" a[3]}
         }
       }}' "$1" | jq -Rn '[inputs | split("\t") | {sha256:.[0], filename:.[1]}]'
}
release_hash() {
    local release=$1 path=$2
    awk -v path="$path" '/^SHA256:/ {section=1; next} section && /^[^ ]/ {section=0}
        section && $3==path {print $1}' "$release"
}

check_source_date() {
    local archive=$1 locked_epoch=$2 scratch=$3 changelog epoch
    # A /dev/stdin tar pipe yields EOF in dpkg's changelog parser. Preserve the
    # identical changelog bytes in a seekable regular file before parsing.
    changelog=$(mktemp "$scratch/source-changelog.XXXXXX") || return 1
    tar -xOf "$archive" debian/changelog > "$changelog" || { rm -f -- "$changelog"; return 1; }
    epoch=$(dpkg-parsechangelog -l "$changelog" -S Timestamp) || { rm -f -- "$changelog"; return 1; }
    rm -f -- "$changelog"
    [[ "$epoch" == "$locked_epoch" ]] || fail 'source date mismatch'
}

validate_schema() {
    jq -e '
      def exact($fields): type == "object" and (keys == ($fields|sort));
      def digest: type == "string" and test("^[0-9a-f]{64}$");
      def fingerprint: type == "string" and test("^[0-9A-F]{40}$");
      def nonempty: type == "string" and length > 0;
      exact(["schema_version","source_version","package_version","architecture","image","snapshot",
        "source_date_epoch","archive_keyring_sha256","maintainer_keyring_sha256","signed_metadata",
        "sources","build_dependencies","toolchain","patches"])
      and .schema_version == 1 and .source_version == "1.24.0-1+deb13u1"
      and .package_version == "1.24.0-1+deb13u1+yoyopod1" and .architecture == "arm64"
      and (.image | type == "string" and test("^docker.io/library/debian@sha256:[0-9a-f]{64}$"))
      and (.snapshot | type == "string" and test("^[0-9]{8}T[0-9]{6}Z$"))
      and (.source_date_epoch | type == "number" and floor == . and . > 0)
      and (.archive_keyring_sha256|digest) and (.maintainer_keyring_sha256|digest)
      and (.signed_metadata | type == "array" and length == 4
        and (map(.kind)|sort) == ["dsc","packages","release","sources"]
        and all(.[]; exact(["kind","request_uri","uri","sha256","signer_fingerprint"])
          and (.sha256|digest) and (.signer_fingerprint|fingerprint) and (.uri|nonempty) and (.request_uri|nonempty)))
      and (.sources | type == "array" and length == 3
        and all(.[]; exact(["name","request_uri","uri","sha256"]) and (.name|nonempty) and (.uri|nonempty) and (.request_uri|nonempty) and (.sha256|digest))
        and (map(.name)|sort) == ["modemmanager_1.24.0-1+deb13u1.debian.tar.xz",
          "modemmanager_1.24.0-1+deb13u1.dsc","modemmanager_1.24.0.orig.tar.xz"])
      and (.build_dependencies | type == "array" and length > 0
        and all(.[]; exact(["name","version","architecture","sha256"])
          and (.name|type == "string" and test("^[a-z0-9][a-z0-9+.-]+$")) and (.version|nonempty)
          and (.architecture == "arm64" or .architecture == "all") and (.sha256|digest))
        and (map(.name)|unique|length) == length)
      and (.toolchain | exact(["gcc","meson","dpkg","image_manifest_sha256","image_index_sha256"])
        and (.gcc|nonempty) and (.meson|nonempty) and (.dpkg|nonempty)
        and (.image_manifest_sha256|digest) and (.image_index_sha256|digest))
      and (.patches | type == "array" and all(.[]; exact(["path","sha256"])
          and (.path | type == "string" and test("^patches/[a-zA-Z0-9._-]+[.]patch$")) and (.sha256|digest)))
    ' "$1" > /dev/null || fail 'missing, unknown or invalid lock fields'
}

validate_request_paths() {
    local lock=$1 base=$2
    jq -e --arg base "$base/" '
      all(.signed_metadata[]|select(.kind!="dsc");
        .request_uri == ($base + (if .kind=="release" then "dists/trixie/InRelease"
          elif .kind=="packages" then "dists/trixie/main/binary-arm64/Packages.xz"
          elif .kind=="sources" then "dists/trixie/main/source/Sources.xz" else "invalid" end)))
      and ([.sources[]|select(.name=="modemmanager_1.24.0-1+deb13u1.dsc")][0] as $dsc |
        any(.signed_metadata[]; .kind=="dsc" and .request_uri==$dsc.request_uri and .uri==$dsc.uri and .sha256==$dsc.sha256))
    ' "$lock" >/dev/null || fail 'metadata kind or descriptor request binding mismatch'
}

publish_verified_source() {
    local lock=$1 dsc=$2 cache=$3 archive_signer=$4 dsc_signer=$5 staged epoch
    # Never preserve previously modified build sources as verified input.
    staged=$(mktemp -d "$cache/staging.XXXXXX") || return 1
    if ! dpkg-source --no-check -x "$dsc" "$staged/source"; then rm -rf -- "$staged"; return 1; fi
    epoch=$(dpkg-parsechangelog -l "$staged/source/debian/changelog" -S Timestamp) || { rm -rf -- "$staged"; return 1; }
    [[ "$epoch" == $(jq -r .source_date_epoch "$lock") ]] || { rm -rf -- "$staged"; fail 'extracted source date mismatch'; return 1; }
    # Finalize the report before publishing source. dpkg-source creates a
    # sibling orig archive inside staging as well as the extracted source.
    jq -n --arg archive "$archive_signer" --arg descriptor "$dsc_signer" --arg lock "$(hash "$lock")" \
       --rawfile archive_set "$cache/metadata/archive-signature.txt.fingerprints" \
       --slurpfile pins "$lock" \
       '{schema_version:1,source_lock_sha256:$lock,archive_signer_fingerprint:$archive,
         archive_signer_fingerprints:($archive_set|split("\n")|map(select(length>0))),descriptor_signer_fingerprint:$descriptor,
         snapshot:$pins[0].snapshot,validated_requests:([$pins[0].signed_metadata[],$pins[0].sources[]]|map({request_uri,uri,sha256}))}' > "$staged/signature-report.json" \
         || { rm -rf -- "$staged"; return 1; }
    rm -rf -- "$cache/source"
    mv -- "$staged/source" "$cache/source" || { rm -rf -- "$staged"; return 1; }
    mv -- "$staged/signature-report.json" "$cache/signature-report.json" || { rm -rf -- "$staged"; return 1; }
    # Remove only our mktemp directory and dpkg-source's sibling copy, keeping
    # the authenticated original downloads and all unrelated cache data.
    rm -rf -- "$staged"
    echo "Verified source staged at $cache/source"
}

verify_inputs() {
    [[ $# == 2 ]] || fail 'usage: verify-inputs.sh LOCK CACHE_DIR'
    local lock cache root snapshot base kind request_uri uri expected name archive_signer dsc_signer dsc
    lock=$(realpath "$1")
    cache=$(realpath -m "$2")
    root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
    validate_schema "$lock"
    snapshot=$(jq -r .snapshot "$lock")
    [[ "$snapshot" < $(date -u +%Y%m%dT%H%M%SZ) ]] || fail 'snapshot must be a fixed historical date'
    base="https://snapshot.debian.org/archive/debian/$snapshot"
    jq -e --arg base "$base/" 'all(.signed_metadata[],.sources[];
        (.request_uri|startswith($base)) and (.uri|test("^https://snapshot[.]debian[.]org/(file/[0-9a-f]{40}/[^/?#]+|archive/debian/[0-9]{8}T[0-9]{6}Z/[^?#]+)$")))' \
        "$lock" >/dev/null || fail 'snapshot request/final URI mismatch'
    validate_request_paths "$lock" "$base"
    [[ $(dpkg --print-architecture) == arm64 ]] || fail 'requires native Debian ARM64 environment'
    [[ ${MM_IMAGE:-} == $(jq -r .image "$lock") ]] || fail 'executing image digest does not match lock'
    [[ $(hash "${MM_IMAGE_INDEX:?official image index required}") == $(jq -r .toolchain.image_index_sha256 "$lock") ]] || fail 'image index bytes mismatch'
    [[ $(hash "${MM_IMAGE_MANIFEST:?official child manifest required}") == $(jq -r .toolchain.image_manifest_sha256 "$lock") ]] || fail 'image manifest bytes mismatch'
    [[ $(hash "$MM_IMAGE_MANIFEST") == "${MM_IMAGE##*@sha256:}" ]] || fail 'image manifest digest mismatch'
    [[ $(gcc -dumpfullversion) == $(jq -r .toolchain.gcc "$lock") && $(meson --version) == $(jq -r .toolchain.meson "$lock") \
       && $(dpkg-query -W -f='${Version}' dpkg) == $(jq -r .toolchain.dpkg "$lock") ]] || fail 'installed toolchain version mismatch'
    [[ $(hash /usr/share/keyrings/debian-archive-keyring.gpg) == $(jq -r .archive_keyring_sha256 "$lock") ]] || fail 'archive keyring hash mismatch'
    [[ $(hash /usr/share/keyrings/debian-keyring.gpg) == $(jq -r .maintainer_keyring_sha256 "$lock") ]] || fail 'maintainer keyring hash mismatch'
    mkdir -p "$cache/downloads" "$cache/metadata"
    # Each invocation rechecks bytes and signatures, including cached bytes.
    for kind in release packages sources; do
        uri=$(jq -r --arg kind "$kind" '.signed_metadata[]|select(.kind==$kind)|.uri' "$lock")
        request_uri=$(jq -r --arg kind "$kind" '.signed_metadata[]|select(.kind==$kind)|.request_uri' "$lock")
        expected=$(jq -r --arg kind "$kind" '.signed_metadata[]|select(.kind==$kind)|.sha256' "$lock")
        fetch "$request_uri" "$cache/metadata/$kind" "$expected" "$uri"
    done
    archive_signer=$(signer /usr/share/keyrings/debian-archive-keyring.gpg "$cache/metadata/release" "$cache/metadata/archive-signature.txt" archive)
    jq -e --arg signer "$archive_signer" 'all(.signed_metadata[]|select(.kind!="dsc"); .signer_fingerprint==$signer)' "$lock" >/dev/null || fail 'archive signer mismatch'
    grep -qx 'Codename: trixie' "$cache/metadata/release" || fail 'unexpected Debian suite'
    for kind in packages sources; do
        if [[ "$kind" == packages ]]; then name=main/binary-arm64/Packages.xz; else name=main/source/Sources.xz; fi
        [[ $(release_hash "$cache/metadata/release" "$name") == $(hash "$cache/metadata/$kind") ]] || fail 'signed Release index hash mismatch'
        xz -dc "$cache/metadata/$kind" > "$cache/metadata/$kind.txt"
    done
    package_index "$cache/metadata/packages.txt" > "$cache/metadata/packages.json"
    source_index "$cache/metadata/sources.txt" > "$cache/metadata/sources.json"
    jq -e --slurpfile index "$cache/metadata/packages.json" '
      all(.build_dependencies[]; . as $pin | any($index[0][];
        .name==$pin.name and .version==$pin.version and .architecture==$pin.architecture and .sha256==$pin.sha256))
    ' "$lock" >/dev/null || fail 'dependency version/hash missing from signed Packages index'
    dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\n' |
        jq -Rn '[inputs|split("\t")|{name:(.[0]|split(":")[0]),version:.[1],architecture:.[2]}]|sort_by(.name)' > "$cache/metadata/installed.json"
    jq -e --slurpfile installed "$cache/metadata/installed.json" \
        '(.build_dependencies|map(del(.sha256))|sort_by(.name))==$installed[0]' "$lock" >/dev/null || fail 'installed dependency closure mismatch'
    jq -e --arg base "$base/" --slurpfile index "$cache/metadata/sources.json" '
      all(.sources[]; . as $pin | any($index[0][]; ($base+.filename)==$pin.request_uri and .sha256==$pin.sha256))
    ' "$lock" >/dev/null || fail 'source missing from signed Sources index'
    jq -e 'any(.sources[]; .name=="modemmanager_1.24.0.orig.tar.xz" and .sha256=="63ded4c0f3936bb0db5ae35ef1dfd57c5d5b4dd8a5cdaa7fb2182255218c9168")
      and any(.sources[]; .name=="modemmanager_1.24.0-1+deb13u1.debian.tar.xz" and .sha256=="0362e74213576b3f830b344f139407843a6caf6b9ae892c5a085a340da6999f2")' "$lock" >/dev/null || fail 'unexpected baseline source archives'
    while IFS=$'\t' read -r name request_uri uri expected; do
        fetch "$request_uri" "$cache/downloads/$name" "$expected" "$uri"
    done < <(jq -r '.sources[]|[.name,.request_uri,.uri,.sha256]|@tsv' "$lock")
    name=modemmanager_1.24.0-1+deb13u1.dsc
    dsc="$cache/downloads/$name"
    dsc_signer=$(signer /usr/share/keyrings/debian-keyring.gpg "$dsc" "$cache/metadata/descriptor-signature.txt")
    jq -e --arg signer "$dsc_signer" --arg uri "$(jq -r --arg name "$name" '.sources[]|select(.name==$name)|.uri' "$lock")" \
        --arg request_uri "$(jq -r --arg name "$name" '.sources[]|select(.name==$name)|.request_uri' "$lock")" \
        --arg sha "$(hash "$cache/downloads/$name")" 'any(.signed_metadata[]; .kind=="dsc" and .signer_fingerprint==$signer and .request_uri==$request_uri and .uri==$uri and .sha256==$sha)' "$lock" >/dev/null || fail 'descriptor signer/hash/request mismatch'
    dscverify --keyring /usr/share/keyrings/debian-keyring.gpg "$dsc"
    check_source_date "$cache/downloads/modemmanager_1.24.0-1+deb13u1.debian.tar.xz" "$(jq -r .source_date_epoch "$lock")" "$cache/metadata"
    while IFS=$'\t' read -r package version architecture expected; do
        uri=$(jq -er --arg name "$package" --arg version "$version" --arg arch "$architecture" '.[]|select(.name==$name and .version==$version and .architecture==$arch)|.filename' "$cache/metadata/packages.json")
        fetch "$base/$uri" "$cache/downloads/${uri##*/}" "$expected"
    done < <(jq -r '.build_dependencies[]|[.name,.version,.architecture,.sha256]|@tsv' "$lock")
    while IFS=$'\t' read -r name expected; do
        [[ $(hash "$root/$name") == "$expected" ]] || fail "local patch hash mismatch: $name"
    done < <(jq -r '.patches[]|[.path,.sha256]|@tsv' "$lock")
    publish_verified_source "$lock" "$dsc" "$cache" "$archive_signer" "$dsc_signer"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then verify_inputs "$@"; fi
