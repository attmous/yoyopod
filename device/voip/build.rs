use std::env;

fn main() {
    println!("cargo:rerun-if-env-changed=PKG_CONFIG_PATH");

    if env::var_os("CARGO_FEATURE_NATIVE_LIBLINPHONE").is_none() {
        return;
    }

    match pkg_config::Config::new()
        .cargo_metadata(false)
        .probe("linphone")
    {
        Ok(_library) => {}
        Err(error) => {
            panic!(
                "native-liblinphone builds require Liblinphone development libraries discoverable by pkg-config: {error}"
            );
        }
    }
}
