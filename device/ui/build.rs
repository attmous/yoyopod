use std::env;
use std::fs;
use std::path::{Path, PathBuf};

fn main() {
    println!("cargo:rerun-if-env-changed=YOYOPOD_LVGL_SOURCE_DIR");
    println!("cargo:rerun-if-env-changed=LVGL_SOURCE_DIR");
    println!("cargo:rerun-if-changed=../../yoyopod/ui/lvgl_binding/native");

    if env::var_os("CARGO_FEATURE_NATIVE_LVGL").is_none() {
        return;
    }

    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let native_dir = normalize_cmake_path(
        manifest_dir
            .join("../../yoyopod/ui/lvgl_binding/native")
            .canonicalize()
            .expect("canonicalize YoYoPod LVGL native directory"),
    );
    let lvgl_source_dir = env::var("YOYOPOD_LVGL_SOURCE_DIR")
        .or_else(|_| env::var("LVGL_SOURCE_DIR"))
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            panic!("native-lvgl requires YOYOPOD_LVGL_SOURCE_DIR or LVGL_SOURCE_DIR to be set")
        });
    let lvgl_source_dir =
        normalize_cmake_path(lvgl_source_dir.canonicalize().unwrap_or_else(|_| {
            panic!(
                "LVGL source directory not found: {}",
                lvgl_source_dir.display()
            )
        }));

    let dst = cmake::Config::new(&native_dir)
        .define("LVGL_SOURCE_DIR", &lvgl_source_dir)
        .define("YOYOPOD_LVGL_BUILD_SHARED", "OFF")
        .build_target("yoyopod_lvgl_shim")
        .build();

    let lvgl_link_dir = find_library_dir(&dst, lvgl_library_file_names()).unwrap_or_else(|| {
        panic!(
            "failed to locate built LVGL library under {}",
            dst.display()
        )
    });
    let shim_link_dir = find_library_dir(&dst, shim_library_file_names()).unwrap_or_else(|| {
        panic!(
            "failed to locate built YoYoPod LVGL shim library under {}",
            dst.display()
        )
    });

    println!("cargo:rustc-link-search=native={}", lvgl_link_dir.display());
    if shim_link_dir != lvgl_link_dir {
        println!("cargo:rustc-link-search=native={}", shim_link_dir.display());
    }
    println!("cargo:rustc-link-lib=yoyopod_lvgl_shim");
    println!("cargo:rustc-link-lib=lvgl");

    if cfg!(target_os = "linux") {
        println!("cargo:rustc-link-lib=m");
        println!(
            "cargo:rustc-link-arg=-Wl,-rpath,{}",
            lvgl_link_dir.display()
        );
        if shim_link_dir != lvgl_link_dir {
            println!(
                "cargo:rustc-link-arg=-Wl,-rpath,{}",
                shim_link_dir.display()
            );
        }
    } else if cfg!(target_os = "macos") {
        println!(
            "cargo:rustc-link-arg=-Wl,-rpath,{}",
            lvgl_link_dir.display()
        );
        if shim_link_dir != lvgl_link_dir {
            println!(
                "cargo:rustc-link-arg=-Wl,-rpath,{}",
                shim_link_dir.display()
            );
        }
    }
}

fn normalize_cmake_path(path: PathBuf) -> PathBuf {
    #[cfg(windows)]
    if let Some(stripped) = path.display().to_string().strip_prefix(r"\\?\") {
        return PathBuf::from(stripped);
    }

    path
}

fn find_library_dir(root: &Path, names: &[&str]) -> Option<PathBuf> {
    if !root.exists() {
        return None;
    }

    let mut stack = vec![root.to_path_buf()];
    while let Some(path) = stack.pop() {
        let entries = fs::read_dir(&path).ok()?;
        for entry in entries.filter_map(Result::ok) {
            let entry_path = entry.path();
            if entry_path.is_dir() {
                stack.push(entry_path);
                continue;
            }

            let file_name = entry.file_name();
            let file_name = file_name.to_string_lossy();
            if names.iter().any(|candidate| file_name == *candidate) {
                return entry_path.parent().map(Path::to_path_buf);
            }
        }
    }

    None
}

fn lvgl_library_file_names() -> &'static [&'static str] {
    if cfg!(target_os = "windows") {
        &["lvgl.lib", "lvgl.dll"]
    } else if cfg!(target_os = "macos") {
        &["liblvgl.dylib", "liblvgl.a"]
    } else {
        &["liblvgl.so", "liblvgl.a"]
    }
}

fn shim_library_file_names() -> &'static [&'static str] {
    if cfg!(target_os = "windows") {
        &["yoyopod_lvgl_shim.lib", "yoyopod_lvgl_shim.dll"]
    } else if cfg!(target_os = "macos") {
        &["libyoyopod_lvgl_shim.dylib", "libyoyopod_lvgl_shim.a"]
    } else {
        &["libyoyopod_lvgl_shim.so", "libyoyopod_lvgl_shim.a"]
    }
}
