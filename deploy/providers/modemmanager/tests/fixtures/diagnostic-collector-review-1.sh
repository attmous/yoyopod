set -euo pipefail
evidence="$GITHUB_WORKSPACE/.artifacts/mm-packages/$PROVIDER_PACKAGE_SHA"
mkdir -p "$evidence/diagnostics"
for build in first second; do
  mkdir -p "$evidence/diagnostics/$build"
  for file in execution.log bootstrap.log output/manifest.json; do
    if test -f "$evidence/$build/$file"; then
      cp -- "$evidence/$build/$file" "$evidence/diagnostics/$build/$(basename "$file")"
    fi
  done
  if test -d "$evidence/$build/output/reports"; then
    find "$evidence/$build/output/reports" -maxdepth 1 -type f \( -name '*.log' -o -name '*.txt' -o -name '*.json' \) \
      -exec cp -- {} "$evidence/diagnostics/$build/" \;
  fi
  if test -d "$evidence/$build/output"; then
    (cd "$evidence/$build/output" && find . -type f -print0 | sort -z | xargs -0 -r sha256sum) > "$evidence/diagnostics/$build/output-sha256.txt"
  fi
done
for file in second/comparison.log second/output.comparison.json; do
  if test -f "$evidence/$file"; then cp -- "$evidence/$file" "$evidence/diagnostics/$(basename "$file")"; fi
done
