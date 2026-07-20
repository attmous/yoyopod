use resvg::{tiny_skia, usvg};
use std::env;
use std::error::Error;
use std::fmt::Write as _;
use std::fs;
use std::path::{Path, PathBuf};

const PREVIEW_CELL_SIZE: u32 = 56;
const ICONS: [IconSpec; 32] = [
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
    IconSpec::new("ask_q", "ASK_Q", 56),
    IconSpec::new("ask_speaker", "ASK_SPEAKER", 56),
    IconSpec::new("ask_cloud_zzz", "ASK_CLOUD_ZZZ", 56),
    IconSpec::new("setup_volume", "SETUP_VOLUME", 56),
    IconSpec::new("setup_companion", "SETUP_COMPANION", 56),
    IconSpec::new("setup_contacts", "SETUP_CONTACTS", 56),
    IconSpec::new("setup_theme", "SETUP_THEME", 56),
    IconSpec::new("setup_speak", "SETUP_SPEAK", 56),
    IconSpec::new("setup_about", "SETUP_ABOUT", 56),
    IconSpec::new("setup_blob", "SETUP_BLOB", 56),
    IconSpec::new("setup_owl", "SETUP_OWL", 56),
    IconSpec::new("setup_cat", "SETUP_CAT", 56),
    IconSpec::new("setup_bunny", "SETUP_BUNNY", 56),
    IconSpec::new("setup_robot", "SETUP_ROBOT", 56),
    IconSpec::new("setup_light", "SETUP_LIGHT", 56),
    IconSpec::new("setup_dark", "SETUP_DARK", 56),
    IconSpec::new("setup_auto", "SETUP_AUTO", 56),
];
const COMPANIONS: [SpriteSpec; 10] = [
    SpriteSpec::new("blob", "COMPANION_BLOB", 114, 114),
    SpriteSpec::new("owl", "COMPANION_OWL", 110, 140),
    SpriteSpec::new("cat", "COMPANION_CAT", 140, 140),
    SpriteSpec::new("bunny", "COMPANION_BUNNY", 120, 160),
    SpriteSpec::new("robot", "COMPANION_ROBOT", 110, 150),
    SpriteSpec::new("dark/blob", "COMPANION_BLOB_DARK", 114, 114),
    SpriteSpec::new("dark/owl", "COMPANION_OWL_DARK", 110, 140),
    SpriteSpec::new("dark/cat", "COMPANION_CAT_DARK", 140, 140),
    SpriteSpec::new("dark/bunny", "COMPANION_BUNNY_DARK", 120, 160),
    SpriteSpec::new("dark/robot", "COMPANION_ROBOT_DARK", 110, 150),
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

#[derive(Clone, Copy)]
struct SpriteSpec {
    file_stem: &'static str,
    rust_name: &'static str,
    width: u32,
    height: u32,
}

impl SpriteSpec {
    const fn new(
        file_stem: &'static str,
        rust_name: &'static str,
        width: u32,
        height: u32,
    ) -> Self {
        Self {
            file_stem,
            rust_name,
            width,
            height,
        }
    }
}

struct RenderedSprite {
    spec: SpriteSpec,
    source_hash: u64,
    rgb565a8: Vec<u8>,
}

fn main() -> Result<(), Box<dyn Error>> {
    let arguments = Arguments::parse()?;
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let ui_dir = manifest_dir.join("../..").canonicalize()?;
    let source_dir = ui_dir.join("assets/icons/listen");
    let output_path = ui_dir.join("src/renderer/lvgl/generated/listen_icons.rs");
    let companion_source_dir = ui_dir.join("assets/icons/companions");
    let companion_output_path = ui_dir.join("src/renderer/lvgl/generated/companion_sprites.rs");

    let icons = ICONS
        .iter()
        .copied()
        .map(|spec| render_icon(&source_dir, spec))
        .collect::<Result<Vec<_>, _>>()?;
    let generated = generated_module(&icons);
    let companions = COMPANIONS
        .iter()
        .copied()
        .map(|spec| render_sprite(&companion_source_dir, spec))
        .collect::<Result<Vec<_>, _>>()?;
    let generated_companions = generated_sprite_module(&companions);

    if arguments.check {
        check_generated(&output_path, &generated)?;
        check_generated(&companion_output_path, &generated_companions)?;
        println!("LVGL icon and companion assets are current");
    } else {
        write_generated(&output_path, &generated)?;
        write_generated(&companion_output_path, &generated_companions)?;
    }

    if let Some(preview_path) = arguments.preview_path {
        write_preview(&icons, &preview_path)?;
        println!("Wrote preview {}", preview_path.display());
    }

    Ok(())
}

fn check_generated(path: &Path, generated: &str) -> Result<(), Box<dyn Error>> {
    let committed = fs::read_to_string(path)
        .map_err(|error| format!("cannot read generated module {}: {error}", path.display()))?;
    if committed != generated {
        return Err(format!("{} is stale; run yoyopod-icon-gen", path.display()).into());
    }
    Ok(())
}

fn write_generated(path: &Path, generated: &str) -> Result<(), Box<dyn Error>> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, generated)?;
    println!("Generated {}", path.display());
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

fn render_sprite(source_dir: &Path, spec: SpriteSpec) -> Result<RenderedSprite, Box<dyn Error>> {
    let source_path = source_dir.join(format!("{}.svg", spec.file_stem));
    let source = fs::read(&source_path)?;
    let tree = usvg::Tree::from_data(&source, &usvg::Options::default())?;
    let natural_size = tree.size().to_int_size();
    if natural_size.width() != spec.width || natural_size.height() != spec.height {
        return Err(format!(
            "{} must render at {}x{}, got {}x{}",
            source_path.display(),
            spec.width,
            spec.height,
            natural_size.width(),
            natural_size.height()
        )
        .into());
    }

    let mut pixmap = tiny_skia::Pixmap::new(spec.width, spec.height)
        .ok_or("failed to allocate companion raster surface")?;
    resvg::render(
        &tree,
        tiny_skia::Transform::identity(),
        &mut pixmap.as_mut(),
    );
    let visible = pixmap
        .pixels()
        .iter()
        .filter(|pixel| pixel.alpha() > 0)
        .count();
    if visible < 1_000 {
        return Err(format!("{} companion is unexpectedly empty", spec.file_stem).into());
    }

    let pixel_count = (spec.width * spec.height) as usize;
    let mut rgb565a8 = Vec::with_capacity(pixel_count * 3);
    for pixel in pixmap.pixels() {
        let color = pixel.demultiply();
        let rgb565 = (u16::from(color.red() >> 3) << 11)
            | (u16::from(color.green() >> 2) << 5)
            | u16::from(color.blue() >> 3);
        rgb565a8.extend_from_slice(&rgb565.to_le_bytes());
    }
    rgb565a8.extend(pixmap.pixels().iter().map(|pixel| pixel.alpha()));

    Ok(RenderedSprite {
        spec,
        source_hash: fnv1a64(&source),
        rgb565a8,
    })
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

fn generated_sprite_module(sprites: &[RenderedSprite]) -> String {
    let mut output = String::from(
        "// @generated by device/ui/tools/icon-gen. Do not edit by hand.\n\
         // Source of truth: device/ui/assets/icons/companions/**/*.svg\n\n",
    );
    for sprite in sprites {
        writeln!(
            output,
            "const {}_SOURCE_FNV1A64: u64 = 0x{:016X};",
            sprite.spec.rust_name, sprite.source_hash
        )
        .unwrap();
        writeln!(
            output,
            "#[rustfmt::skip]\nstatic {}_MAP: [u8; {}] = [",
            sprite.spec.rust_name,
            sprite.rgb565a8.len()
        )
        .unwrap();
        for row in sprite.rgb565a8.chunks(16) {
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
