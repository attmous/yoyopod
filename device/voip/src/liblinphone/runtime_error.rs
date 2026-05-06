use std::cell::RefCell;
use std::ffi::CString;
use std::os::raw::c_char;

thread_local! {
    static LAST_ERROR: RefCell<CString> =
        RefCell::new(CString::new("no error").expect("static error string"));
}

pub fn set_last_error(message: impl AsRef<str>) {
    let sanitized = message.as_ref().replace('\0', " ");
    LAST_ERROR.with(|slot| {
        *slot.borrow_mut() = CString::new(sanitized).expect("nul bytes were sanitized");
    });
}

pub fn clear_last_error() {
    set_last_error("");
}

pub fn last_error_ptr() -> *const c_char {
    LAST_ERROR.with(|slot| slot.borrow().as_ptr())
}
