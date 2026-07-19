# UI icon assets

The SVG files in this directory are the editable source of truth for LVGL
alpha-only (`A8`) icon masks. LVGL does not parse these files on the device.
Instead, the Rust icon generator rasterizes each SVG at its final pixel size
and writes the antialiased alpha bytes into the generated Rust module.

Wheel icons use a `56 x 56` view box and compact controls use `24 x 24`.
Both use the same rounded-line visual language across Listen and Talk. Keep
the artwork monochrome: runtime colour comes from LVGL image recolouring.

Regenerate the masks and a local review strip with:

```text
cargo run --manifest-path device/ui/tools/icon-gen/Cargo.toml --locked -- \
  --preview temp/listen-icons.png
```

Verify that committed output is current without writing files:

```text
cargo run --manifest-path device/ui/tools/icon-gen/Cargo.toml --locked -- --check
```

The `yoyopod-ui` tests also compare an FNV-1a hash of every SVG against the
generated module, so changing artwork without regenerating fails locally and
in CI.
