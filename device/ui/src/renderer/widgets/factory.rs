use std::ffi::CString;
use std::ptr::{self, NonNull};

use anyhow::{anyhow, Result};

use crate::renderer::lvgl::ffi;
use crate::renderer::widgets::WidgetRole;
pub(crate) fn create_root_object() -> Result<NonNull<ffi::lv_obj_t>> {
    non_null(
        unsafe { ffi::lv_obj_create(ptr::null_mut()) },
        "root widget",
    )
}

pub(crate) fn create_container_object(
    parent: NonNull<ffi::lv_obj_t>,
    role: WidgetRole,
) -> Result<NonNull<ffi::lv_obj_t>> {
    non_null(
        unsafe { ffi::lv_obj_create(parent.as_ptr()) },
        format!("container for {role}"),
    )
}

pub(crate) fn create_label_object(
    parent: NonNull<ffi::lv_obj_t>,
    role: WidgetRole,
) -> Result<NonNull<ffi::lv_obj_t>> {
    let obj = non_null(
        unsafe { ffi::lv_label_create(parent.as_ptr()) },
        format!("label for {role}"),
    )?;
    let empty = CString::new("").expect("empty CString");
    unsafe {
        ffi::lv_label_set_text(obj.as_ptr(), empty.as_ptr());
    }
    Ok(obj)
}

pub(crate) fn create_image_object(
    parent: NonNull<ffi::lv_obj_t>,
    role: WidgetRole,
) -> Result<NonNull<ffi::lv_obj_t>> {
    let obj = non_null(
        unsafe { ffi::lv_image_create(parent.as_ptr()) },
        format!("image for {role}"),
    )?;
    Ok(obj)
}

pub(crate) fn create_arc_object(
    parent: NonNull<ffi::lv_obj_t>,
    role: WidgetRole,
) -> Result<NonNull<ffi::lv_obj_t>> {
    non_null(
        unsafe { ffi::lv_arc_create(parent.as_ptr()) },
        format!("arc for {role}"),
    )
}

fn non_null(
    obj: *mut ffi::lv_obj_t,
    context: impl std::fmt::Display,
) -> Result<NonNull<ffi::lv_obj_t>> {
    NonNull::new(obj).ok_or_else(|| anyhow!("LVGL {context} creation failed"))
}
