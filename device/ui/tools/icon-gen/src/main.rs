use resvg::{tiny_skia, usvg};
use std::env;
use std::error::Error;
use std::fmt::Write as _;
use std::fs;
use std::path::{Path, PathBuf};

const PREVIEW_CELL_SIZE: u32 = 56;
const ICONS: [IconSpec; 15] = [
    IconSpec::new("playlists", "PLAYLISTS", 56),
    IconSpec::new("recents", "RECENTS", 56),
    IconSpec::new("shuffle", "SHUFFLE", 56),
    IconSpec::new("microphone", "MICROPHONE", 56),
    IconSpec::new("plus", "PLUS", 56),
    IconSpec::new("music_note", "MUSIC_NOTE", 56),
    IconSpec::new("play", "PLAY", 56),
    IconSpec::new("play_sm", "PLAY_SM", 24),
    IconSpec::new("pause_sm", "PAUSE_SM", 24),
    IconSpec::new("prev_sm", "PREV_SM", 24),
    IconSpec::new("next_sm", "NEXT_SM", 24),
    IconSpec::new("trash_sm", "TRASH_SM", 24),
    IconSpec::new("answer_sm", "ANSWER_SM", 24),
    IconSpec::new("close_sm", "CLOSE_SM", 24),
    IconSpec::new("mic_sm", "MIC_SM", 24),
];

#[derive(Clone, Copy)]
struct IconSpec {
    file_stem: &'static str,
    rust_name: &'static str,
    size: u32,
}

impl IconSpec {
    const fn new(file_stem: &'static str, rust_name: &'static str, size: u32) -> Self {
        Self {
            file_stem,
            rust_name,
            size,
        }
    }
}

struct RenderedIcon {
    spec: IconSpec,
    source_hash: u64,
    alpha: Vec<u8>,
    pixmap: tiny_skia::Pixmap,
}

fn main() -> Result<(), Box<dyn Error>> {
    let arguments = Arguments::parse()?;
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let ui_dir = manifest_dir.join("../..").canonicalize()?;
    let source_dir = ui_dir.join("assets/icons/listen");
    let output_path = ui_dir.join("src/renderer/lvgl/generated/listen_icons.rs");

    let icons = ICONS
        .iter()
        .copied()
        .map(|spec| render_icon(&source_dir, spec))
        .collect::<Result<Vec<_>, _>>()?;
    let generated = generated_module(&icons);

    if arguments.check {
        let committed = fs::read_to_string(&output_path).map_err(|error| {
            format!(
                "cannot read generated icon module {}: {error}",
                output_path.display()
            )
        })?;
        if committed != generated {
            return Err(format!("{} is stale; run yoyopod-icon-gen", output_path.display()).into());
        }
        println!("Listen icon masks are current: {}", output_path.display());
    } else {
        if let Some(parent) = output_path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(&output_path, generated)?;
        println!("Generated {}", output_path.display());
    }

    if let Some(preview_path) = arguments.preview_path {
        write_preview(&icons, &preview_path)?;
        println!("Wrote preview {}", preview_path.display());
    }

    Ok(())
}

struct Arguments {
    check: bool,
    preview_path: Option<PathBuf>,
}

impl Arguments {
    fn parse() -> Result<Self, Box<dyn Error>> {
        let mut check = false;
        let mut preview_path = None;
        let mut args = env::args().skip(1);
        while let Some(argument) = args.next() {
            match argument.as_str() {
                "--check" => check = true,
                "--preview" => {
                    let path = args.next().ok_or("--preview requires a PNG path")?;
                    preview_path = Some(PathBuf::from(path));
                }
                "--help" | "-h" => {
                    println!("Usage: yoyopod-icon-gen [--check] [--preview <path.png>]");
                    std::process::exit(0);
                }
                _ => return Err(format!("unknown argument: {argument}").into()),
            }
        }
        Ok(Self {
            check,
            preview_path,
        })
    }
}

fn render_icon(source_dir: &Path, spec: IconSpec) -> Result<RenderedIcon, Box<dyn Error>> {
    let source_path = source_dir.join(format!("{}.svg", spec.file_stem));
    let source = fs::read(&source_path)?;
    let options = usvg::Options::default();
    let tree = usvg::Tree::from_data(&source, &options)?;
    let natural_size = tree.size().to_int_size();
    if natural_size.width() != spec.size || natural_size.height() != spec.size {
        return Err(format!(
            "{} must have a {}x{} viewport, got {}x{}",
            source_path.display(),
            spec.size,
            spec.size,
            natural_size.width(),
            natural_size.height()
        )
        .into());
    }

    let mut pixmap = tiny_skia::Pixmap::new(spec.size, spec.size)
        .ok_or("failed to allocate icon raster surface")?;
    resvg::render(
        &tree,
        tiny_skia::Transform::identity(),
        &mut pixmap.as_mut(),
    );
    let alpha = pixmap
        .data()
        .chunks_exact(4)
        .map(|pixel| pixel[3])
        .collect::<Vec<_>>();
    validate_alpha(spec, &alpha)?;

    Ok(RenderedIcon {
        spec,
        source_hash: fnv1a64(&source),
        alpha,
        pixmap,
    })
}

fn validate_alpha(spec: IconSpec, alpha: &[u8]) -> Result<(), Box<dyn Error>> {
    let visible = alpha.iter().filter(|value| **value > 0).count();
    let antialiased = alpha
        .iter()
        .filter(|value| **value > 0 && **value < u8::MAX)
        .count();
    let minimum_visible = if spec.size <= 24 { 32 } else { 80 };
    if visible < minimum_visible {
        return Err(format!("{} icon is unexpectedly empty", spec.file_stem).into());
    }
    if antialiased < 12 {
        return Err(format!("{} icon lost antialiasing", spec.file_stem).into());
    }
    Ok(())
}

fn generated_module(icons: &[RenderedIcon]) -> String {
    let mut output = String::from(
        "// @generated by device/ui/tools/icon-gen. Do not edit by hand.\n\
         // Source of truth: device/ui/assets/icons/listen/*.svg\n\n",
    );
    for icon in icons {
        writeln!(
            output,
            "const {}_SOURCE_FNV1A64: u64 = 0x{:016X};",
            icon.spec.rust_name, icon.source_hash
        )
        .unwrap();
        writeln!(
            output,
            "#[rustfmt::skip]\nstatic {}_MAP: [u8; {}] = [",
            icon.spec.rust_name,
            icon.spec.size * icon.spec.size
        )
        .unwrap();
        for row in icon.alpha.chunks(16) {
            output.push_str("    ");
            for (index, value) in row.iter().enumerate() {
                if index > 0 {
                    output.push(' ');
                }
                write!(output, "0x{value:02X},").unwrap();
            }
            output.push('\n');
        }
        output.push_str("];\n\n");
    }
    while output.ends_with('\n') {
        output.pop();
    }
    output.push('\n');
    output
}

fn write_preview(icons: &[RenderedIcon], path: &Path) -> Result<(), Box<dyn Error>> {
    const GUTTER: u32 = 8;
    let width = GUTTER + icons.len() as u32 * (PREVIEW_CELL_SIZE + GUTTER);
    let height = PREVIEW_CELL_SIZE + GUTTER * 2;
    let mut preview =
        tiny_skia::Pixmap::new(width, height).ok_or("failed to allocate icon preview surface")?;
    preview.fill(tiny_skia::Color::from_rgba8(246, 242, 235, 255));

    for (index, icon) in icons.iter().enumerate() {
        preview.draw_pixmap(
            (GUTTER
                + index as u32 * (PREVIEW_CELL_SIZE + GUTTER)
                + (PREVIEW_CELL_SIZE - icon.spec.size) / 2) as i32,
            (GUTTER + (PREVIEW_CELL_SIZE - icon.spec.size) / 2) as i32,
            icon.pixmap.as_ref(),
            &tiny_skia::PixmapPaint::default(),
            tiny_skia::Transform::identity(),
            None,
        );
    }
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent)?;
    }
    preview.save_png(path)?;
    Ok(())
}

fn fnv1a64(bytes: &[u8]) -> u64 {
    let mut hash = 0xCBF29CE484222325u64;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001B3);
    }
    hash
}
