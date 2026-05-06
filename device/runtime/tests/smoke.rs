use yoyopod_runtime::runtime_name;

#[test]
fn runtime_crate_exports_stable_name() {
    assert_eq!(runtime_name(), "yoyopod-runtime");
}
