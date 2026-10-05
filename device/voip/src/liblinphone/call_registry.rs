use std::collections::BTreeMap;

pub(crate) struct SessionRegistry<H> {
    calls: BTreeMap<String, H>,
}

impl<H> Default for SessionRegistry<H> {
    fn default() -> Self {
        Self::new()
    }
}

impl<H> SessionRegistry<H> {
    pub fn new() -> Self {
        Self {
            calls: BTreeMap::new(),
        }
    }
    pub fn insert(&mut self, call_id: String, handle: H) -> Result<(), String> {
        if call_id.is_empty() || self.calls.contains_key(&call_id) || self.is_full() {
            return Err("empty or duplicate call ID".into());
        }
        self.calls.insert(call_id, handle);
        Ok(())
    }
    pub fn is_full(&self) -> bool {
        self.calls.len() >= yoyopod_protocol::call::MAX_LIVE_CALLS
    }
    pub fn get(&self, call_id: &str) -> Option<&H> {
        self.calls.get(call_id)
    }
    #[cfg(feature = "native-liblinphone")]
    pub fn get_mut(&mut self, call_id: &str) -> Option<&mut H> {
        self.calls.get_mut(call_id)
    }
    pub fn remove(&mut self, call_id: &str) -> Option<H> {
        self.calls.remove(call_id)
    }
    #[cfg(feature = "native-liblinphone")]
    pub fn iter(&self) -> impl Iterator<Item = (&String, &H)> {
        self.calls.iter()
    }
}

#[cfg(feature = "native-liblinphone")]
pub(crate) struct NativeCallHandle {
    pub ptr: *mut super::ffi::LinphoneCall,
    api: std::sync::Arc<super::ffi::LinphoneApi>,
    pub incoming: bool,
    pub connected: bool,
    pub terminal: bool,
}

#[cfg(feature = "native-liblinphone")]
impl NativeCallHandle {
    /// Called only by the host thread, with a live borrowed Liblinphone call.
    pub unsafe fn retain(
        ptr: *mut super::ffi::LinphoneCall,
        api: std::sync::Arc<super::ffi::LinphoneApi>,
        incoming: bool,
    ) -> Self {
        Self {
            ptr: unsafe { (api.call_ref)(ptr) },
            api,
            incoming,
            connected: false,
            terminal: false,
        }
    }
}

#[cfg(feature = "native-liblinphone")]
impl Drop for NativeCallHandle {
    fn drop(&mut self) {
        unsafe { (self.api.call_unref)(self.ptr) };
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn capacity_refusal_preserves_live_handles_and_release_removes_ownership() {
        let mut calls = SessionRegistry::new();
        for id in 0..64 {
            calls.insert(id.to_string(), id).unwrap();
        }
        assert!(calls.is_full());
        for id in 64..10_000 {
            assert!(calls.insert(id.to_string(), id).is_err());
        }
        assert_eq!(calls.get("0"), Some(&0));
        assert_eq!(calls.remove("0"), Some(0));
        assert!(calls.get("0").is_none());
        assert!(!calls.is_full());
        calls.insert("10000".into(), 10000).unwrap();
        assert_eq!(calls.get("1"), Some(&1));
    }

    #[test]
    fn duplicate_insertion_and_removal_drop_each_owned_handle_once() {
        use std::{cell::Cell, rc::Rc};
        struct Handle(Rc<Cell<usize>>);
        impl Drop for Handle {
            fn drop(&mut self) {
                self.0.set(self.0.get() + 1);
            }
        }
        let drops = Rc::new(Cell::new(0));
        let mut calls = SessionRegistry::new();
        calls.insert("a".into(), Handle(drops.clone())).unwrap();
        assert!(calls.insert("a".into(), Handle(drops.clone())).is_err());
        assert_eq!(drops.get(), 1);
        let owned = calls.remove("a").unwrap();
        assert_eq!(drops.get(), 1);
        drop(owned);
        drop(calls);
        assert_eq!(drops.get(), 2);
    }

    #[test]
    fn removing_second_call_preserves_first_handle() {
        let mut calls = SessionRegistry::new();
        calls.insert("a".into(), 101_u64).unwrap();
        calls.insert("b".into(), 202_u64).unwrap();
        assert_eq!(calls.remove("b"), Some(202));
        assert_eq!(calls.get("a"), Some(&101));
        assert!(calls.get("b").is_none());
    }
}
