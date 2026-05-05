use super::ffi::{
    self, LinphoneAccount, LinphoneAddress, LinphoneApi, LinphoneCall, LinphoneChatMessage,
    LinphoneChatRoom, LinphoneContent, LinphoneCore, LinphoneEventLog, LinphoneRecorderParams,
};
use super::{abi_event as event, runtime_error as error, state};
use once_cell::sync::Lazy;
use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int, c_void};
use std::ptr;
use std::sync::Arc;

pub use super::abi_event::YoyopodLiblinphoneEvent;

const FALSE: c_int = 0;
const TRUE: c_int = 1;
const LINPHONE_REASON_DECLINED: c_int = 4;
const LINPHONE_RECORDER_FILE_FORMAT_WAV: c_int = 0;

static VERSION: &[u8] = b"yoyopod-voip-host-liblinphone/0.1.0\0";
static STATE: Lazy<std::sync::Mutex<state::ShimState>> =
    Lazy::new(|| std::sync::Mutex::new(state::ShimState::new()));

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_version() -> *const c_char {
    if let Ok(state) = STATE.lock() {
        if let Some(api) = state.api.as_ref() {
            let version = unsafe { (api.core_get_version)() };
            if !version.is_null() {
                return version;
            }
        }
    }
    VERSION.as_ptr().cast()
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_last_error() -> *const c_char {
    error::last_error_ptr()
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_init() -> c_int {
    let mut state = match STATE.lock() {
        Ok(state) => state,
        Err(_) => {
            error::set_last_error("liblinphone runtime state lock poisoned");
            return -1;
        }
    };
    if state.initialized {
        return 0;
    }
    let api = match unsafe { LinphoneApi::load() } {
        Ok(api) => api,
        Err(message) => {
            error::set_last_error(message);
            return -1;
        }
    };
    let factory = unsafe { (api.factory_get)() };
    if factory.is_null() {
        error::set_last_error("failed to get Liblinphone factory");
        return -1;
    }
    state.api = Some(api);
    state.factory = factory;
    state.initialized = true;
    error::clear_last_error();
    0
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_shutdown() {
    unsafe { yoyopod_liblinphone_stop() };
    if let Ok(mut state) = STATE.lock() {
        *state = state::ShimState::new();
    }
}

#[allow(clippy::too_many_arguments)]
#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_start(
    sip_server: *const c_char,
    sip_username: *const c_char,
    sip_password: *const c_char,
    sip_password_ha1: *const c_char,
    sip_identity: *const c_char,
    factory_config_path: *const c_char,
    transport: *const c_char,
    stun_server: *const c_char,
    conference_factory_uri: *const c_char,
    file_transfer_server_url: *const c_char,
    lime_server_url: *const c_char,
    auto_download_incoming_voice_recordings: i32,
    playback_device_id: *const c_char,
    ringer_device_id: *const c_char,
    capture_device_id: *const c_char,
    media_device_id: *const c_char,
    echo_cancellation: i32,
    mic_gain: i32,
    output_volume: i32,
    voice_note_store_dir: *const c_char,
) -> c_int {
    if unsafe { yoyopod_liblinphone_init() } != 0 {
        return -1;
    }

    let mut state = match STATE.lock() {
        Ok(state) => state,
        Err(_) => {
            error::set_last_error("liblinphone runtime state lock poisoned");
            return -1;
        }
    };
    if state.started {
        return 0;
    }

    let sip_server_value = unsafe { ptr_to_string(sip_server) };
    let sip_identity_value = unsafe { ptr_to_string(sip_identity) };
    if sip_server_value.is_empty() || sip_identity_value.is_empty() {
        error::set_last_error("missing SIP identity or SIP server for Liblinphone startup");
        return -1;
    }
    let api = match state.api.clone() {
        Some(api) => api,
        None => {
            error::set_last_error("Liblinphone API is not initialized");
            return -1;
        }
    };

    let factory_config = optional_cstring(unsafe { ptr_to_string(factory_config_path) });
    state.core = unsafe {
        (api.factory_create_core_3)(
            state.factory,
            ptr::null(),
            factory_config
                .as_ref()
                .map_or(ptr::null(), |value| value.as_ptr()),
            ptr::null_mut(),
        )
    };
    if state.core.is_null() {
        error::set_last_error("failed to create Liblinphone core");
        return -1;
    }

    if !create_callbacks(&mut state, &api) {
        stop_locked(&mut state);
        return -1;
    }

    let voice_note_dir = unsafe { ptr_to_string(voice_note_store_dir) };
    state.auto_download_incoming_voice_recordings = auto_download_incoming_voice_recordings != 0;
    state.voice_note_store_dir = voice_note_dir.clone();
    if !voice_note_dir.is_empty() {
        let _ = std::fs::create_dir_all(&voice_note_dir);
    }

    unsafe {
        set_device(
            &api,
            state.core,
            playback_device_id,
            api.core_set_playback_device,
        );
        set_device(
            &api,
            state.core,
            ringer_device_id,
            api.core_set_ringer_device,
        );
        set_device(
            &api,
            state.core,
            capture_device_id,
            api.core_set_capture_device,
        );
        set_device(&api, state.core, media_device_id, api.core_set_media_device);
        (api.core_enable_chat)(state.core);
        (api.core_enable_echo_cancellation)(
            state.core,
            if echo_cancellation != 0 { TRUE } else { FALSE },
        );
        (api.core_set_mic_gain_db)(state.core, (mic_gain as f32) * 0.3);
        (api.core_set_playback_gain_db)(state.core, ((output_volume as f32) * 0.12) - 6.0);
        (api.core_set_audio_port_range)(state.core, 7076, 7100);
        (api.core_set_video_port_range)(state.core, 9076, 9100);
        if let Some(set_aggregation) = api.core_set_chat_messages_aggregation_enabled {
            set_aggregation(state.core, FALSE);
        }
        if let Some(auto_download) = api.core_enable_auto_download_voice_recordings {
            auto_download(state.core, FALSE);
        }
        if let (Some(policy_fn), Some(enable_all)) =
            (api.core_get_im_notif_policy, api.im_notif_policy_enable_all)
        {
            let policy = policy_fn(state.core);
            if !policy.is_null() {
                enable_all(policy);
            }
        }
        if let Some(add_spec) = api.core_add_linphone_spec {
            if let Ok(spec) = CString::new("conference/2.0") {
                add_spec(state.core, spec.as_ptr());
            }
        }
    }

    if configure_network(&api, state.core, unsafe { ptr_to_string(stun_server) }) != 0 {
        stop_locked(&mut state);
        return -1;
    }

    let account_result = configure_account(
        &mut state,
        &api,
        AccountConfig {
            sip_server: sip_server_value,
            sip_username: unsafe { ptr_to_string(sip_username) },
            sip_password: unsafe { ptr_to_string(sip_password) },
            sip_password_ha1: unsafe { ptr_to_string(sip_password_ha1) },
            sip_identity: sip_identity_value,
            transport: unsafe { ptr_to_string(transport) },
            conference_factory_uri: unsafe { ptr_to_string(conference_factory_uri) },
            file_transfer_server_url: unsafe { ptr_to_string(file_transfer_server_url) },
            lime_server_url: unsafe { ptr_to_string(lime_server_url) },
        },
    );
    if account_result != 0 {
        stop_locked(&mut state);
        return -1;
    }

    if unsafe { (api.core_start)(state.core) } != 0 {
        error::set_last_error("Liblinphone core failed to start");
        stop_locked(&mut state);
        return -1;
    }
    state.started = true;
    error::clear_last_error();
    0
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_stop() {
    if let Ok(mut state) = STATE.lock() {
        stop_locked(&mut state);
    }
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_iterate() {
    let snapshot = STATE.lock().ok().and_then(|state| {
        if state.started && !state.core.is_null() {
            state.api.clone().map(|api| (api, state.core))
        } else {
            None
        }
    });
    if let Some((api, core)) = snapshot {
        unsafe { (api.core_iterate)(core) };
    }
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_poll_event(
    event_out: *mut event::YoyopodLiblinphoneEvent,
) -> c_int {
    if event_out.is_null() {
        return 0;
    }
    let state = match STATE.lock() {
        Ok(state) => state,
        Err(_) => return 0,
    };
    if !state.initialized {
        return 0;
    }
    match state.queue.pop() {
        Some(value) => {
            unsafe { *event_out = value };
            1
        }
        None => 0,
    }
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_make_call(sip_address: *const c_char) -> c_int {
    let sip_address_value = unsafe { ptr_to_string(sip_address) };
    let (api, factory, core) = match state_handles() {
        Ok(handles) => handles,
        Err(message) => {
            error::set_last_error(message);
            return -1;
        }
    };
    if sip_address_value.is_empty() {
        error::set_last_error("Liblinphone core is not ready to place a call");
        return -1;
    }
    let address_value = match CString::new(sip_address_value) {
        Ok(value) => value,
        Err(_) => {
            error::set_last_error("invalid SIP address for outgoing call");
            return -1;
        }
    };
    let address = unsafe { (api.factory_create_address)(factory, address_value.as_ptr()) };
    if address.is_null() {
        error::set_last_error("invalid SIP address for outgoing call");
        return -1;
    }
    let params = unsafe { (api.core_create_call_params)(core, ptr::null_mut()) };
    if params.is_null() {
        unsafe { (api.address_unref)(address) };
        error::set_last_error("failed to create Liblinphone call params");
        return -1;
    }
    let call = unsafe { (api.core_invite_address_with_params)(core, address, params) };
    unsafe {
        (api.call_params_unref)(params);
        (api.address_unref)(address);
    }
    if call.is_null() {
        error::set_last_error("Liblinphone failed to initiate outgoing call");
        return -1;
    }
    if let Ok(mut state) = STATE.lock() {
        state.current_call = call;
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_answer_call() -> c_int {
    with_current_call(
        "No incoming call is available to answer",
        |api, call| unsafe { (api.call_accept)(call) },
    )
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_reject_call() -> c_int {
    with_current_call(
        "No incoming call is available to reject",
        |api, call| unsafe { (api.call_decline)(call, LINPHONE_REASON_DECLINED) },
    )
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_hangup() -> c_int {
    with_current_call(
        "No active call is available to hang up",
        |api, call| unsafe { (api.call_terminate)(call) },
    )
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_set_muted(muted: i32) -> c_int {
    with_current_call("No active call is available to mute", |api, call| unsafe {
        (api.call_set_microphone_muted)(call, if muted != 0 { TRUE } else { FALSE });
        0
    })
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_send_text_message(
    sip_address: *const c_char,
    text: *const c_char,
    message_id_out: *mut c_char,
    message_id_out_size: u32,
) -> c_int {
    let sip_address_value = unsafe { ptr_to_string(sip_address) };
    let text_value = unsafe { ptr_to_string(text) };
    if sip_address_value.is_empty() || text.is_null() {
        error::set_last_error("Liblinphone text message send is missing peer or payload");
        return -1;
    }
    let message = match create_chat_message(&sip_address_value, |_state, api, chat_room| {
        let text = CString::new(text_value.as_str())
            .map_err(|_| "Liblinphone text payload contains an interior NUL".to_string())?;
        let message = unsafe { (api.chat_room_create_message_from_utf8)(chat_room, text.as_ptr()) };
        if message.is_null() {
            Err("Liblinphone failed to create a text chat message".to_string())
        } else {
            Ok(message)
        }
    }) {
        Ok((api, message_id, message)) => {
            copy_str_to_c_buffer(&message_id, message_id_out, message_id_out_size);
            unsafe { (api.chat_message_send)(message) };
            return 0;
        }
        Err(message) => message,
    };
    error::set_last_error(message);
    -1
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_start_voice_recording(
    file_path: *const c_char,
) -> c_int {
    let file_path_value = unsafe { ptr_to_string(file_path) };
    if file_path_value.is_empty() {
        error::set_last_error(
            "Liblinphone voice-note recording requires an active core and target path",
        );
        return -1;
    }
    let mut state = match STATE.lock() {
        Ok(state) => state,
        Err(_) => {
            error::set_last_error("liblinphone runtime state lock poisoned");
            return -1;
        }
    };
    if !state.started || state.core.is_null() {
        error::set_last_error(
            "Liblinphone voice-note recording requires an active core and target path",
        );
        return -1;
    }
    cleanup_recorder(&mut state);
    let api = match state.api.clone() {
        Some(api) => api,
        None => {
            error::set_last_error("Liblinphone API is not initialized");
            return -1;
        }
    };
    let params = match unsafe { create_recorder_params(&api, state.core) } {
        Ok(params) => params,
        Err(message) => {
            error::set_last_error(message);
            return -1;
        }
    };
    let recorder = unsafe {
        api.core_create_recorder
            .expect("recorder symbol was checked")(state.core, params)
    };
    if let Some(unref) = api.recorder_params_unref {
        unsafe { unref(params) };
    }
    if recorder.is_null() {
        error::set_last_error("failed to create Liblinphone recorder");
        return -1;
    }
    state.current_recorder = recorder;
    state.current_recording_path = file_path_value.clone();
    if !state.voice_note_store_dir.is_empty() {
        let _ = std::fs::create_dir_all(&state.voice_note_store_dir);
    }
    let file_path = match CString::new(file_path_value) {
        Ok(value) => value,
        Err(_) => {
            error::set_last_error("voice-note path contains an interior NUL");
            cleanup_recorder(&mut state);
            return -1;
        }
    };
    let open = api.recorder_open.expect("recorder symbol was checked");
    let start = api.recorder_start.expect("recorder symbol was checked");
    if unsafe { open(recorder, file_path.as_ptr()) } != 0 {
        error::set_last_error("failed to open voice-note file for recording");
        cleanup_recorder(&mut state);
        return -1;
    }
    if unsafe { start(recorder) } != 0 {
        error::set_last_error("failed to start voice-note recording");
        cleanup_recorder(&mut state);
        return -1;
    }
    state.recorder_running = true;
    0
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_stop_voice_recording(
    duration_ms_out: *mut i32,
) -> c_int {
    let mut state = match STATE.lock() {
        Ok(state) => state,
        Err(_) => {
            error::set_last_error("liblinphone runtime state lock poisoned");
            return -1;
        }
    };
    if !state.started || state.current_recorder.is_null() || !state.recorder_running {
        error::set_last_error("No active Liblinphone voice-note recording is running");
        return -1;
    }
    let api = state.api.clone().expect("initialized state has API");
    let pause = match api.recorder_pause {
        Some(function) => function,
        None => {
            error::set_last_error(
                "installed Liblinphone build does not support recorder-based voice notes",
            );
            return -1;
        }
    };
    let duration = api.recorder_get_duration;
    let close = api.recorder_close;
    unsafe { pause(state.current_recorder) };
    state.recorder_running = false;
    let duration_ms = duration.map_or(0, |function| unsafe { function(state.current_recorder) });
    if let Some(function) = close {
        unsafe { function(state.current_recorder) };
    }
    if !duration_ms_out.is_null() {
        unsafe { *duration_ms_out = duration_ms };
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_cancel_voice_recording() -> c_int {
    if let Ok(mut state) = STATE.lock() {
        if !state.current_recording_path.is_empty() {
            let _ = std::fs::remove_file(&state.current_recording_path);
        }
        cleanup_recorder(&mut state);
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn yoyopod_liblinphone_send_voice_note(
    sip_address: *const c_char,
    file_path: *const c_char,
    _duration_ms: i32,
    _mime_type: *const c_char,
    message_id_out: *mut c_char,
    message_id_out_size: u32,
) -> c_int {
    let sip_address_value = unsafe { ptr_to_string(sip_address) };
    let requested_path = unsafe { ptr_to_string(file_path) };
    if sip_address_value.is_empty() {
        error::set_last_error(
            "Liblinphone voice-note send requires a closed recording and recipient",
        );
        return -1;
    }
    let message = match create_chat_message(&sip_address_value, |state, api, chat_room| {
        let recorder = state.current_recorder;
        let recording_path = state.current_recording_path.clone();
        let running = state.recorder_running;
        if recorder.is_null() {
            return Err(
                "Liblinphone voice-note send requires a closed recording and recipient".to_string(),
            );
        }
        if running {
            return Err("Voice-note recording must be stopped before sending".to_string());
        }
        if !requested_path.is_empty() && requested_path != recording_path {
            return Err(
                "Voice-note send only supports the active recorder output in this build"
                    .to_string(),
            );
        }
        if !std::path::Path::new(&recording_path).exists() {
            return Err(format!(
                "voice-note file does not exist at {recording_path}"
            ));
        }
        let create = api
            .chat_room_create_voice_recording_message
            .ok_or_else(|| {
                "installed Liblinphone build does not support recorder-based voice notes"
                    .to_string()
            })?;
        let message = unsafe { create(chat_room, recorder) };
        if message.is_null() {
            Err("Liblinphone failed to create a voice-note message".to_string())
        } else {
            Ok(message)
        }
    }) {
        Ok((api, message_id, message)) => {
            copy_str_to_c_buffer(&message_id, message_id_out, message_id_out_size);
            unsafe { (api.chat_message_send)(message) };
            return 0;
        }
        Err(message) => message,
    };
    error::set_last_error(message);
    -1
}

struct AccountConfig {
    sip_server: String,
    sip_username: String,
    sip_password: String,
    sip_password_ha1: String,
    sip_identity: String,
    transport: String,
    conference_factory_uri: String,
    file_transfer_server_url: String,
    lime_server_url: String,
}

fn create_callbacks(state: &mut state::ShimState, api: &LinphoneApi) -> bool {
    state.core_cbs = unsafe { (api.factory_create_core_cbs)(state.factory) };
    if state.core_cbs.is_null() {
        error::set_last_error("failed to create Liblinphone core callbacks");
        return false;
    }
    state.message_cbs = unsafe { (api.chat_message_cbs_new)() };
    if state.message_cbs.is_null() {
        error::set_last_error("failed to create Liblinphone chat message callbacks");
        return false;
    }
    state.chat_room_cbs = unsafe { (api.factory_create_chat_room_cbs)(state.factory) };
    if state.chat_room_cbs.is_null() {
        error::set_last_error("failed to create Liblinphone chat room callbacks");
        return false;
    }
    unsafe {
        (api.chat_message_cbs_set_msg_state_changed)(
            state.message_cbs,
            Some(on_message_state_changed),
        );
        (api.chat_room_cbs_set_message_received)(
            state.chat_room_cbs,
            Some(on_chat_room_message_received),
        );
        if let Some(set_messages_received) = api.chat_room_cbs_set_messages_received {
            set_messages_received(state.chat_room_cbs, Some(on_chat_room_messages_received));
        }
        if let Some(set_chat_message_received) = api.chat_room_cbs_set_chat_message_received {
            set_chat_message_received(
                state.chat_room_cbs,
                Some(on_chat_room_chat_message_received),
            );
        }
        (api.core_cbs_set_call_state_changed)(state.core_cbs, Some(on_call_state_changed));
        (api.core_cbs_set_message_received)(state.core_cbs, Some(on_message_received));
        if let Some(set_unable_decrypt) = api.core_cbs_set_message_received_unable_decrypt {
            set_unable_decrypt(state.core_cbs, Some(on_message_received_unable_decrypt));
        }
        (api.core_add_callbacks)(state.core, state.core_cbs);
    }
    true
}

fn configure_network(api: &LinphoneApi, core: *mut LinphoneCore, stun_server: String) -> c_int {
    unsafe {
        let nat_policy = (api.core_create_nat_policy)(core);
        if nat_policy.is_null() {
            error::set_last_error("failed to create Liblinphone NAT policy");
            return -1;
        }
        (api.nat_policy_enable_stun)(nat_policy, TRUE);
        (api.nat_policy_enable_ice)(nat_policy, TRUE);
        if let Some(stun) = optional_cstring(stun_server.as_str()) {
            (api.nat_policy_set_stun_server)(nat_policy, stun.as_ptr());
            (api.core_set_stun_server)(core, stun.as_ptr());
        }
        (api.core_set_nat_policy)(core, nat_policy);
        (api.nat_policy_unref)(nat_policy);
    }
    0
}

fn configure_account(
    state: &mut state::ShimState,
    api: &LinphoneApi,
    config: AccountConfig,
) -> c_int {
    let transport = if config.transport.is_empty() || config.transport == "auto" {
        "tcp"
    } else {
        config.transport.as_str()
    };
    let server_uri = format!("sip:{};transport={transport}", config.sip_server);
    let server_uri = match CString::new(server_uri) {
        Ok(value) => value,
        Err(_) => {
            error::set_last_error("SIP server URI contains an interior NUL");
            return -1;
        }
    };
    let identity = match CString::new(config.sip_identity.as_str()) {
        Ok(value) => value,
        Err(_) => {
            error::set_last_error("SIP identity contains an interior NUL");
            return -1;
        }
    };

    unsafe {
        let params = (api.core_create_account_params)(state.core);
        if params.is_null() {
            error::set_last_error("failed to create Linphone account params");
            return -1;
        }
        let server_address = (api.factory_create_address)(state.factory, server_uri.as_ptr());
        let identity_address = (api.factory_create_address)(state.factory, identity.as_ptr());
        if server_address.is_null() || identity_address.is_null() {
            cleanup_account_params(
                api,
                params,
                server_address,
                identity_address,
                ptr::null_mut(),
            );
            error::set_last_error("failed to create Linphone account addresses");
            return -1;
        }
        if (api.account_params_set_server_address)(params, server_address) != 0
            || (api.account_params_set_identity_address)(params, identity_address) != 0
        {
            cleanup_account_params(
                api,
                params,
                server_address,
                identity_address,
                ptr::null_mut(),
            );
            error::set_last_error("failed to set Linphone account addresses");
            return -1;
        }
        (api.account_params_enable_register)(params, TRUE);
        if let Some(enable_cpim) = api.account_params_enable_cpim_in_basic_chat_room {
            enable_cpim(params, TRUE);
        }
        let conference_address = set_conference_factory(state, api, params, &config);
        set_account_optional_urls(state, api, params, &config);
        let account = (api.core_create_account)(state.core, params);
        if account.is_null() {
            cleanup_account_params(
                api,
                params,
                server_address,
                identity_address,
                conference_address,
            );
            error::set_last_error("failed to create Linphone account");
            return -1;
        }
        state.account_cbs = (api.account_cbs_new)();
        if state.account_cbs.is_null() {
            cleanup_account_params(
                api,
                params,
                server_address,
                identity_address,
                conference_address,
            );
            (api.account_unref)(account);
            error::set_last_error("failed to create Linphone account callbacks");
            return -1;
        }
        (api.account_cbs_set_registration_state_changed)(
            state.account_cbs,
            Some(on_registration_state_changed),
        );
        (api.account_add_callbacks)(account, state.account_cbs);
        add_auth_info(state, api, &config);
        if (api.core_add_account)(state.core, account) != 0 {
            cleanup_account_params(
                api,
                params,
                server_address,
                identity_address,
                conference_address,
            );
            (api.account_unref)(account);
            error::set_last_error("failed to add Linphone account to core");
            return -1;
        }
        (api.core_set_default_account)(state.core, account);
        state.account = account;
        cleanup_account_params(
            api,
            params,
            server_address,
            identity_address,
            conference_address,
        );
    }
    0
}

unsafe fn cleanup_account_params(
    api: &LinphoneApi,
    params: *mut ffi::LinphoneAccountParams,
    server_address: *mut LinphoneAddress,
    identity_address: *mut LinphoneAddress,
    conference_address: *mut LinphoneAddress,
) {
    if !server_address.is_null() {
        unsafe { (api.address_unref)(server_address) };
    }
    if !identity_address.is_null() {
        unsafe { (api.address_unref)(identity_address) };
    }
    if !conference_address.is_null() {
        unsafe { (api.address_unref)(conference_address) };
    }
    if !params.is_null() {
        unsafe { (api.account_params_unref)(params) };
    }
}

unsafe fn set_conference_factory(
    state: &mut state::ShimState,
    api: &LinphoneApi,
    params: *mut ffi::LinphoneAccountParams,
    config: &AccountConfig,
) -> *mut LinphoneAddress {
    state.configured_conference_factory_uri = config.conference_factory_uri.clone();
    if config.conference_factory_uri.is_empty() {
        return ptr::null_mut();
    }
    let conference_uri = match CString::new(config.conference_factory_uri.as_str()) {
        Ok(value) => value,
        Err(_) => return ptr::null_mut(),
    };
    let address = unsafe { (api.factory_create_address)(state.factory, conference_uri.as_ptr()) };
    if address.is_null() {
        return ptr::null_mut();
    }
    if let Some(set_conference) = api.account_params_set_conference_factory_address {
        unsafe { set_conference(params, address) };
    }
    if let Some(set_av_conference) = api.account_params_set_audio_video_conference_factory_address {
        unsafe { set_av_conference(params, address) };
    }
    address
}

unsafe fn set_account_optional_urls(
    state: &mut state::ShimState,
    api: &LinphoneApi,
    params: *mut ffi::LinphoneAccountParams,
    config: &AccountConfig,
) {
    state.configured_file_transfer_server_url = config.file_transfer_server_url.clone();
    state.configured_lime_server_url = config.lime_server_url.clone();
    if let Some(url) = optional_cstring(config.file_transfer_server_url.as_str()) {
        if let Some(set_file_transfer_server) = api.account_params_set_file_transfer_server {
            unsafe { set_file_transfer_server(params, url.as_ptr()) };
        }
        unsafe { (api.core_set_file_transfer_server)(state.core, url.as_ptr()) };
    }
    let lime_enabled = !config.lime_server_url.is_empty();
    if let Some(enable_lime) = api.core_enable_lime_x3dh {
        unsafe { enable_lime(state.core, if lime_enabled { TRUE } else { FALSE }) };
    }
    if let (true, Some(set_lime), Some(url)) = (
        lime_enabled,
        api.account_params_set_lime_server_url,
        optional_cstring(config.lime_server_url.as_str()),
    ) {
        unsafe { set_lime(params, url.as_ptr()) };
    }
}

unsafe fn add_auth_info(state: &state::ShimState, api: &LinphoneApi, config: &AccountConfig) {
    let username = optional_cstring(config.sip_username.as_str());
    let password = optional_cstring(config.sip_password.as_str());
    let password_ha1 = optional_cstring(config.sip_password_ha1.as_str());
    let server = optional_cstring(config.sip_server.as_str());
    let algorithm = CString::new("SHA-256").expect("static algorithm");
    if username.is_none() || server.is_none() {
        return;
    }
    let username = username.expect("checked above");
    let server = server.expect("checked above");
    let auth_info = unsafe {
        (api.factory_create_auth_info_2)(
            state.factory,
            username.as_ptr(),
            username.as_ptr(),
            password
                .as_ref()
                .map_or(ptr::null(), |value| value.as_ptr()),
            password_ha1
                .as_ref()
                .map_or(ptr::null(), |value| value.as_ptr()),
            server.as_ptr(),
            server.as_ptr(),
            algorithm.as_ptr(),
        )
    };
    if !auth_info.is_null() {
        unsafe {
            (api.core_add_auth_info)(state.core, auth_info);
            (api.auth_info_unref)(auth_info);
        }
    }
}

fn stop_locked(state: &mut state::ShimState) {
    let api = match state.api.clone() {
        Some(api) => api,
        None => {
            state.reset_runtime();
            return;
        }
    };
    unsafe {
        if !state.core.is_null() {
            (api.core_stop)(state.core);
        }
    }
    cleanup_recorder(state);
    unsafe {
        if !state.account_cbs.is_null() {
            (api.account_cbs_unref)(state.account_cbs);
        }
        if !state.message_cbs.is_null() {
            (api.chat_message_cbs_unref)(state.message_cbs);
        }
        if !state.chat_room_cbs.is_null() {
            (api.chat_room_cbs_unref)(state.chat_room_cbs);
        }
        if !state.core_cbs.is_null() {
            (api.core_cbs_unref)(state.core_cbs);
        }
        if !state.account.is_null() {
            (api.account_unref)(state.account);
        }
        if !state.core.is_null() {
            (api.core_unref)(state.core);
        }
    }
    state.reset_runtime();
}

fn cleanup_recorder(state: &mut state::ShimState) {
    let Some(api) = state.api.clone() else {
        state.current_recorder = ptr::null_mut();
        state.recorder_running = false;
        state.current_recording_path.clear();
        return;
    };
    if !state.current_recorder.is_null() {
        unsafe {
            if state.recorder_running {
                if let Some(pause) = api.recorder_pause {
                    pause(state.current_recorder);
                }
            }
            if let Some(close) = api.recorder_close {
                close(state.current_recorder);
            }
            if let Some(unref) = api.recorder_unref {
                unref(state.current_recorder);
            }
        }
    }
    state.current_recorder = ptr::null_mut();
    state.recorder_running = false;
    state.current_recording_path.clear();
}

unsafe fn create_recorder_params(
    api: &LinphoneApi,
    core: *mut LinphoneCore,
) -> Result<*mut LinphoneRecorderParams, String> {
    let create_params = api.core_create_recorder_params.ok_or_else(|| {
        "installed Liblinphone build does not support recorder-based voice notes".to_string()
    })?;
    if api.core_create_recorder.is_none()
        || api.recorder_open.is_none()
        || api.recorder_start.is_none()
        || api.recorder_pause.is_none()
    {
        return Err(
            "installed Liblinphone build does not support recorder-based voice notes".to_string(),
        );
    }
    let params = unsafe { create_params(core) };
    if params.is_null() {
        return Err("failed to create Liblinphone recorder params".to_string());
    }
    if let Some(set_format) = api.recorder_params_set_file_format {
        unsafe { set_format(params, LINPHONE_RECORDER_FILE_FORMAT_WAV) };
    }
    Ok(params)
}

fn state_handles() -> Result<
    (
        Arc<LinphoneApi>,
        *mut ffi::LinphoneFactory,
        *mut LinphoneCore,
    ),
    String,
> {
    let state = STATE
        .lock()
        .map_err(|_| "liblinphone runtime state lock poisoned".to_string())?;
    if !state.started || state.core.is_null() {
        return Err("Liblinphone core is not ready".to_string());
    }
    let api = state
        .api
        .clone()
        .ok_or_else(|| "Liblinphone API is not initialized".to_string())?;
    Ok((api, state.factory, state.core))
}

fn with_current_call(
    missing_message: &str,
    function: impl FnOnce(&LinphoneApi, *mut LinphoneCall) -> c_int,
) -> c_int {
    let (api, call) = match STATE.lock() {
        Ok(state) if state.started && !state.current_call.is_null() => {
            let api = state.api.clone().expect("started state has API");
            (api, state.current_call)
        }
        _ => {
            error::set_last_error(missing_message);
            return -1;
        }
    };
    let status = function(&api, call);
    if status == 0 {
        0
    } else {
        error::set_last_error(missing_message);
        -1
    }
}

fn create_chat_message(
    sip_address: &str,
    build: impl FnOnce(
        &mut state::ShimState,
        &LinphoneApi,
        *mut LinphoneChatRoom,
    ) -> Result<*mut LinphoneChatMessage, String>,
) -> Result<(Arc<LinphoneApi>, String, *mut LinphoneChatMessage), String> {
    let mut state = STATE
        .lock()
        .map_err(|_| "liblinphone runtime state lock poisoned".to_string())?;
    if !state.started || state.core.is_null() {
        return Err("Liblinphone text message send is missing peer or payload".to_string());
    }
    let api = state
        .api
        .clone()
        .ok_or_else(|| "Liblinphone API is not initialized".to_string())?;
    let sip_address = CString::new(sip_address)
        .map_err(|_| "SIP address contains an interior NUL".to_string())?;
    let chat_room = unsafe { (api.core_get_chat_room_from_uri)(state.core, sip_address.as_ptr()) };
    if chat_room.is_null() {
        return Err(format!(
            "Liblinphone could not resolve a chat room for {}",
            sip_address.to_string_lossy()
        ));
    }
    attach_chat_room_callbacks(&mut state, &api, chat_room);
    let message = build(&mut state, &api, chat_room)?;
    attach_message_callbacks(&state, &api, message);
    let message_id = build_message_id(&mut state, &api, message);
    Ok((api, message_id, message))
}

fn attach_chat_room_callbacks(
    state: &mut state::ShimState,
    api: &LinphoneApi,
    chat_room: *mut LinphoneChatRoom,
) {
    if chat_room.is_null()
        || state.chat_room_cbs.is_null()
        || state
            .attached_chat_rooms
            .iter()
            .any(|attached| *attached == chat_room)
    {
        return;
    }
    unsafe { (api.chat_room_add_callbacks)(chat_room, state.chat_room_cbs) };
    state.attached_chat_rooms.push(chat_room);
}

fn attach_message_callbacks(
    state: &state::ShimState,
    api: &LinphoneApi,
    message: *mut LinphoneChatMessage,
) {
    if !message.is_null() && !state.message_cbs.is_null() {
        unsafe { (api.chat_message_add_callbacks)(message, state.message_cbs) };
    }
}

fn build_message_id(
    state: &mut state::ShimState,
    api: &LinphoneApi,
    message: *mut LinphoneChatMessage,
) -> String {
    let message_id = unsafe { cstr_to_string((api.chat_message_get_message_id)(message)) };
    if !message_id.is_empty() {
        return message_id;
    }
    let user_data = unsafe { (api.chat_message_get_user_data)(message) };
    if !user_data.is_null() {
        let value = unsafe { cstr_to_string(user_data.cast::<c_char>()) };
        if !value.is_empty() {
            return value;
        }
    }
    state.message_counter += 1;
    let generated = format!(
        "local-{}-{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_secs())
            .unwrap_or_default(),
        state.message_counter
    );
    if let Ok(value) = CString::new(generated.as_str()) {
        unsafe { (api.chat_message_set_user_data)(message, value.into_raw().cast::<c_void>()) };
    }
    generated
}

unsafe extern "C" fn on_registration_state_changed(
    _account: *mut LinphoneAccount,
    registration_state: c_int,
    message: *const c_char,
) {
    let Ok(state) = STATE.lock() else {
        return;
    };
    let Some(api) = state.api.clone() else {
        return;
    };
    let mut event = YoyopodLiblinphoneEvent {
        event_type: event::EVENT_REGISTRATION,
        registration_state: map_registration_state(&api, registration_state),
        ..Default::default()
    };
    copy_str_to_fixed(&unsafe { ptr_to_string(message) }, &mut event.reason);
    state.queue.push(event);
}

unsafe extern "C" fn on_call_state_changed(
    _core: *mut LinphoneCore,
    call: *mut LinphoneCall,
    call_state: c_int,
    message: *const c_char,
) {
    let Ok(mut state) = STATE.lock() else {
        return;
    };
    let Some(api) = state.api.clone() else {
        return;
    };
    state.current_call = call;
    let mapped = map_call_state(&api, call_state);
    let mut event = YoyopodLiblinphoneEvent {
        event_type: event::EVENT_CALL_STATE,
        call_state: mapped,
        ..Default::default()
    };
    if !call.is_null() {
        let address = unsafe { (api.call_get_remote_address)(call) };
        copy_str_to_fixed(
            &build_address_uri(&api, address),
            &mut event.peer_sip_address,
        );
    }
    copy_str_to_fixed(&unsafe { ptr_to_string(message) }, &mut event.reason);
    state.queue.push(event);
    if mapped == event::CALL_INCOMING {
        let mut incoming = YoyopodLiblinphoneEvent {
            event_type: event::EVENT_INCOMING_CALL,
            ..Default::default()
        };
        copy_str_to_fixed(
            &c_array_to_string(&event.peer_sip_address),
            &mut incoming.peer_sip_address,
        );
        state.queue.push(incoming);
    }
    if matches!(
        mapped,
        event::CALL_RELEASED | event::CALL_END | event::CALL_ERROR
    ) {
        state.current_call = ptr::null_mut();
    }
}

unsafe extern "C" fn on_message_received(
    _core: *mut LinphoneCore,
    _chat_room: *mut LinphoneChatRoom,
    message: *mut LinphoneChatMessage,
) {
    queue_message_received(message);
}

unsafe extern "C" fn on_message_received_unable_decrypt(
    _core: *mut LinphoneCore,
    _chat_room: *mut LinphoneChatRoom,
    _message: *mut LinphoneChatMessage,
) {
}

unsafe extern "C" fn on_chat_room_message_received(
    _chat_room: *mut LinphoneChatRoom,
    message: *mut LinphoneChatMessage,
) {
    queue_message_received(message);
}

unsafe extern "C" fn on_chat_room_messages_received(
    _chat_room: *mut LinphoneChatRoom,
    _messages: *const c_void,
) {
}

unsafe extern "C" fn on_chat_room_chat_message_received(
    _chat_room: *mut LinphoneChatRoom,
    event_log: *mut LinphoneEventLog,
) {
    let Some((api, message)) = STATE.lock().ok().and_then(|state| {
        let api = state.api.clone()?;
        let get_message = api.event_log_get_chat_message?;
        let message = unsafe { get_message(event_log) };
        Some((api, message))
    }) else {
        return;
    };
    drop(api);
    queue_message_received(message);
}

unsafe extern "C" fn on_message_state_changed(
    message: *mut LinphoneChatMessage,
    message_state: c_int,
) {
    let Ok(mut state) = STATE.lock() else {
        return;
    };
    let Some(api) = state.api.clone() else {
        return;
    };
    let mut event = YoyopodLiblinphoneEvent {
        event_type: event::EVENT_MESSAGE_DELIVERY_CHANGED,
        ..Default::default()
    };
    fill_message_event_common(&mut state, &api, &mut event, message);
    event.message_delivery_state = map_message_delivery_state(&api, message_state);
    if event.message_delivery_state == event::MESSAGE_DELIVERY_FAILED {
        let reason = unsafe { cstr_to_string((api.chat_message_state_to_string)(message_state)) };
        copy_str_to_fixed(&reason, &mut event.reason);
    }
    state.queue.push(event);
    if event.message_delivery_state == event::MESSAGE_DELIVERY_SENT {
        let mut downloaded = YoyopodLiblinphoneEvent {
            event_type: event::EVENT_MESSAGE_DOWNLOAD_COMPLETED,
            ..Default::default()
        };
        fill_message_event_common(&mut state, &api, &mut downloaded, message);
        state.queue.push(downloaded);
    }
}

fn queue_message_received(message: *mut LinphoneChatMessage) {
    let Ok(mut state) = STATE.lock() else {
        return;
    };
    let Some(api) = state.api.clone() else {
        return;
    };
    let mut event = YoyopodLiblinphoneEvent {
        event_type: event::EVENT_MESSAGE_RECEIVED,
        unread: if unsafe { (api.chat_message_is_read)(message) } != 0 {
            0
        } else {
            1
        },
        ..Default::default()
    };
    attach_message_callbacks(&state, &api, message);
    fill_message_event_common(&mut state, &api, &mut event, message);
    prepare_auto_download(&state, &api, message);
    state.queue.push(event);
}

fn fill_message_event_common(
    state: &mut state::ShimState,
    api: &LinphoneApi,
    event: &mut YoyopodLiblinphoneEvent,
    message: *mut LinphoneChatMessage,
) {
    if message.is_null() {
        return;
    }
    let content = unsafe { (api.chat_message_get_file_transfer_information)(message) };
    event.message_kind = message_kind(api, message, content);
    event.message_direction = if unsafe { (api.chat_message_is_outgoing)(message) } != 0 {
        event::MESSAGE_DIRECTION_OUTGOING
    } else {
        event::MESSAGE_DIRECTION_INCOMING
    };
    event.message_delivery_state =
        map_message_delivery_state(api, unsafe { (api.chat_message_get_state)(message) });
    let message_id = build_message_id(state, api, message);
    copy_str_to_fixed(&message_id, &mut event.message_id);
    copy_str_to_fixed(
        &build_address_uri(api, unsafe { (api.chat_message_get_peer_address)(message) }),
        &mut event.peer_sip_address,
    );
    copy_str_to_fixed(
        &build_address_uri(api, unsafe { (api.chat_message_get_from_address)(message) }),
        &mut event.sender_sip_address,
    );
    copy_str_to_fixed(
        &build_address_uri(api, unsafe { (api.chat_message_get_to_address)(message) }),
        &mut event.recipient_sip_address,
    );
    copy_str_to_fixed(&chat_message_text(api, message), &mut event.text);
    if event.message_kind == event::MESSAGE_KIND_VOICE_NOTE {
        let mime = voice_note_payload_mime(api, message, content);
        copy_str_to_fixed(
            if mime.is_empty() { "audio/wav" } else { &mime },
            &mut event.mime_type,
        );
        event.duration_ms = extract_voice_note_duration_ms(&chat_message_text(api, message));
        if is_file_transfer_xml_content(api, content) {
            event.text = [0; 1024];
        }
    } else {
        copy_str_to_fixed(&mime_type(api, content), &mut event.mime_type);
    }
    if !content.is_null() {
        copy_str_to_fixed(
            &unsafe { cstr_to_string((api.content_get_file_path)(content)) },
            &mut event.local_file_path,
        );
    }
}

fn prepare_auto_download(
    state: &state::ShimState,
    api: &LinphoneApi,
    message: *mut LinphoneChatMessage,
) {
    if !state.auto_download_incoming_voice_recordings || message.is_null() {
        return;
    }
    let content = unsafe { (api.chat_message_get_file_transfer_information)(message) };
    if !is_voice_note_message(api, message, content) || content.is_null() {
        return;
    }
    let message_id = unsafe { cstr_to_string((api.chat_message_get_message_id)(message)) };
    if message_id.is_empty() || state.voice_note_store_dir.is_empty() {
        return;
    }
    let mime = voice_note_payload_mime(api, message, content);
    let extension = voice_note_extension(&chat_message_text(api, message), &mime);
    let path = format!(
        "{}/{}.{}",
        state.voice_note_store_dir, message_id, extension
    );
    let _ = std::fs::create_dir_all(&state.voice_note_store_dir);
    if let Ok(path_c) = CString::new(path) {
        unsafe {
            (api.content_set_file_path)(content, path_c.as_ptr());
            (api.chat_message_download_content)(message, content);
        }
    }
}

fn build_address_uri(api: &LinphoneApi, address: *const LinphoneAddress) -> String {
    if address.is_null() {
        return String::new();
    }
    let username = unsafe { cstr_to_string((api.address_get_username)(address)) };
    let domain = unsafe { cstr_to_string((api.address_get_domain)(address)) };
    if !username.is_empty() && !domain.is_empty() {
        format!("sip:{username}@{domain}")
    } else if !domain.is_empty() {
        format!("sip:{domain}")
    } else {
        String::new()
    }
}

fn message_kind(
    api: &LinphoneApi,
    message: *mut LinphoneChatMessage,
    content: *mut LinphoneContent,
) -> i32 {
    if is_voice_note_message(api, message, content) {
        event::MESSAGE_KIND_VOICE_NOTE
    } else {
        event::MESSAGE_KIND_TEXT
    }
}

fn is_voice_note_message(
    api: &LinphoneApi,
    message: *mut LinphoneChatMessage,
    content: *mut LinphoneContent,
) -> bool {
    if is_voice_note_content(api, content) {
        return true;
    }
    is_file_transfer_xml_content(api, content)
        && chat_message_text(api, message).contains("voice-recording=yes")
}

fn is_voice_note_content(api: &LinphoneApi, content: *mut LinphoneContent) -> bool {
    !content.is_null()
        && unsafe { cstr_to_string((api.content_get_type)(content)) }.eq_ignore_ascii_case("audio")
}

fn is_file_transfer_xml_content(api: &LinphoneApi, content: *mut LinphoneContent) -> bool {
    if content.is_null() {
        return false;
    }
    let media_type = unsafe { cstr_to_string((api.content_get_type)(content)) };
    let subtype = unsafe { cstr_to_string((api.content_get_subtype)(content)) };
    media_type == "application" && subtype == "vnd.gsma.rcs-ft-http+xml"
}

fn mime_type(api: &LinphoneApi, content: *mut LinphoneContent) -> String {
    if content.is_null() {
        return String::new();
    }
    let media_type = unsafe { cstr_to_string((api.content_get_type)(content)) };
    let subtype = unsafe { cstr_to_string((api.content_get_subtype)(content)) };
    if !media_type.is_empty() && !subtype.is_empty() {
        format!("{media_type}/{subtype}")
    } else {
        media_type
    }
}

fn voice_note_payload_mime(
    api: &LinphoneApi,
    message: *mut LinphoneChatMessage,
    content: *mut LinphoneContent,
) -> String {
    if is_voice_note_content(api, content) {
        return mime_type(api, content);
    }
    extract_tag_text(
        &chat_message_text(api, message),
        "<content-type>",
        "</content-type>",
    )
    .and_then(|value| value.split(';').next().map(str::trim).map(str::to_string))
    .unwrap_or_default()
}

fn voice_note_extension(xml_text: &str, mime: &str) -> String {
    if let Some(file_name) = extract_tag_text(xml_text, "<file-name>", "</file-name>") {
        if let Some(extension) = file_name
            .rsplit('.')
            .next()
            .filter(|value| *value != file_name)
        {
            if !extension.is_empty() {
                return extension.to_string();
            }
        }
    }
    mime.split_once('/')
        .map(|(_, extension)| extension)
        .filter(|value| !value.is_empty())
        .unwrap_or("wav")
        .to_string()
}

fn extract_voice_note_duration_ms(xml_text: &str) -> i32 {
    extract_tag_text(xml_text, "<am:playing-length>", "</am:playing-length>")
        .and_then(|value| value.parse::<i32>().ok())
        .unwrap_or_default()
}

fn extract_tag_text<'a>(xml_text: &'a str, opening: &str, closing: &str) -> Option<&'a str> {
    let start = xml_text.find(opening)? + opening.len();
    let rest = &xml_text[start..];
    let end = rest.find(closing)?;
    Some(&rest[..end])
}

fn chat_message_text(api: &LinphoneApi, message: *mut LinphoneChatMessage) -> String {
    if message.is_null() {
        return String::new();
    }
    unsafe {
        if let Some(get_utf8_text) = api.chat_message_get_utf8_text {
            let value = cstr_to_string(get_utf8_text(message));
            if !value.is_empty() {
                return value;
            }
        }
        api.chat_message_get_text
            .map(|get_text| cstr_to_string(get_text(message)))
            .unwrap_or_default()
    }
}

fn map_registration_state(api: &LinphoneApi, state: c_int) -> c_int {
    let state_text = api
        .registration_state_to_string
        .map(|function| unsafe { cstr_to_string(function(state)) })
        .unwrap_or_default()
        .to_ascii_lowercase();
    if state_text.contains("ok") {
        event::REGISTRATION_OK
    } else if state_text.contains("progress") {
        event::REGISTRATION_PROGRESS
    } else if state_text.contains("cleared") {
        event::REGISTRATION_CLEARED
    } else if state_text.contains("failed") {
        event::REGISTRATION_FAILED
    } else {
        match state {
            1 => event::REGISTRATION_PROGRESS,
            2 => event::REGISTRATION_OK,
            3 => event::REGISTRATION_CLEARED,
            4 => event::REGISTRATION_FAILED,
            _ => event::REGISTRATION_NONE,
        }
    }
}

fn map_call_state(api: &LinphoneApi, state: c_int) -> c_int {
    let state_text = api
        .call_state_to_string
        .map(|function| unsafe { cstr_to_string(function(state)) })
        .unwrap_or_default()
        .to_ascii_lowercase();
    if state_text.contains("incoming") {
        event::CALL_INCOMING
    } else if state_text.contains("outgoinginit") {
        event::CALL_OUTGOING_INIT
    } else if state_text.contains("outgoingprogress") {
        event::CALL_OUTGOING_PROGRESS
    } else if state_text.contains("outgoingringing") {
        event::CALL_OUTGOING_RINGING
    } else if state_text.contains("outgoingearlymedia") {
        event::CALL_OUTGOING_EARLY_MEDIA
    } else if state_text.contains("streamsrunning") {
        event::CALL_STREAMS_RUNNING
    } else if state_text.contains("connected") {
        event::CALL_CONNECTED
    } else if state_text.contains("pausedbyremote") {
        event::CALL_PAUSED_BY_REMOTE
    } else if state_text.contains("paused") {
        event::CALL_PAUSED
    } else if state_text.contains("updat") {
        event::CALL_UPDATED_BY_REMOTE
    } else if state_text.contains("released") {
        event::CALL_RELEASED
    } else if state_text.contains("error") {
        event::CALL_ERROR
    } else if state_text.contains("end") {
        event::CALL_END
    } else {
        match state {
            1 => event::CALL_INCOMING,
            2 => event::CALL_OUTGOING_INIT,
            3 => event::CALL_OUTGOING_PROGRESS,
            4 => event::CALL_OUTGOING_RINGING,
            5 => event::CALL_OUTGOING_EARLY_MEDIA,
            6 => event::CALL_CONNECTED,
            7 => event::CALL_STREAMS_RUNNING,
            8 => event::CALL_PAUSED,
            9 => event::CALL_PAUSED_BY_REMOTE,
            10 => event::CALL_UPDATED_BY_REMOTE,
            11 => event::CALL_RELEASED,
            12 => event::CALL_ERROR,
            13 => event::CALL_END,
            _ => event::CALL_IDLE,
        }
    }
}

fn map_message_delivery_state(api: &LinphoneApi, state: c_int) -> c_int {
    let state_text =
        unsafe { cstr_to_string((api.chat_message_state_to_string)(state)) }.to_ascii_lowercase();
    if state_text.contains("notdelivered")
        || state_text.contains("transfererror")
        || state_text.contains("error")
    {
        event::MESSAGE_DELIVERY_FAILED
    } else if state_text.contains("inprogress") || state_text.contains("transferinprogress") {
        event::MESSAGE_DELIVERY_SENDING
    } else if state_text.contains("deliveredtouser") || state_text.contains("displayed") {
        event::MESSAGE_DELIVERY_DELIVERED
    } else if state_text.contains("delivered") || state_text.contains("transferdone") {
        event::MESSAGE_DELIVERY_SENT
    } else if state_text.contains("idle") || state_text.contains("queued") {
        event::MESSAGE_DELIVERY_QUEUED
    } else {
        event::MESSAGE_DELIVERY_FAILED
    }
}

unsafe fn set_device(
    _api: &LinphoneApi,
    core: *mut LinphoneCore,
    value: *const c_char,
    setter: unsafe extern "C" fn(*mut LinphoneCore, *const c_char),
) {
    if !value.is_null() {
        unsafe { setter(core, value) };
    }
}

fn optional_cstring(value: impl AsRef<str>) -> Option<CString> {
    let value = value.as_ref();
    if value.is_empty() {
        None
    } else {
        CString::new(value).ok()
    }
}

unsafe fn ptr_to_string(value: *const c_char) -> String {
    if value.is_null() {
        return String::new();
    }
    unsafe { CStr::from_ptr(value) }
        .to_string_lossy()
        .into_owned()
}

unsafe fn cstr_to_string(value: *const c_char) -> String {
    unsafe { ptr_to_string(value) }
}

fn copy_str_to_fixed<const N: usize>(value: &str, out: &mut [c_char; N]) {
    *out = [0; N];
    let bytes = value.as_bytes();
    let count = bytes.len().min(N.saturating_sub(1));
    unsafe {
        std::ptr::copy_nonoverlapping(bytes.as_ptr(), out.as_mut_ptr().cast::<u8>(), count);
    }
}

fn c_array_to_string<const N: usize>(value: &[c_char; N]) -> String {
    unsafe { CStr::from_ptr(value.as_ptr()) }
        .to_string_lossy()
        .into_owned()
}

fn copy_str_to_c_buffer(value: &str, out: *mut c_char, out_size: u32) -> bool {
    if out.is_null() || out_size == 0 {
        return false;
    }
    let bytes = value.as_bytes();
    let writable = out_size.saturating_sub(1) as usize;
    let count = bytes.len().min(writable);
    unsafe {
        std::ptr::copy_nonoverlapping(bytes.as_ptr(), out.cast::<u8>(), count);
        *out.add(count) = 0;
    }
    true
}
