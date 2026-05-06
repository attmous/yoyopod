load("@crates//:defs.bzl", "aliases", "all_crate_deps")
load("@rules_rust//rust:defs.bzl", "rust_binary", "rust_library")

def yoyopod_rust_host_library(name, srcs, crate_root = "src/lib.rs", deps = None, **kwargs):
    if deps == None:
        deps = []
    rust_library(
        name = name,
        crate_root = crate_root,
        srcs = srcs,
        aliases = aliases(normal = True, proc_macro = True),
        deps = deps + all_crate_deps(normal = True),
        proc_macro_deps = all_crate_deps(proc_macro = True),
        edition = "2021",
        visibility = ["//visibility:public"],
        **kwargs
    )

def yoyopod_rust_host_binary(name, srcs, crate_root = "src/main.rs", deps = None, **kwargs):
    if deps == None:
        deps = []
    rust_binary(
        name = name,
        crate_root = crate_root,
        srcs = srcs,
        aliases = aliases(normal = True, proc_macro = True),
        deps = deps + all_crate_deps(normal = True),
        proc_macro_deps = all_crate_deps(proc_macro = True),
        edition = "2021",
        visibility = ["//visibility:public"],
        **kwargs
    )
