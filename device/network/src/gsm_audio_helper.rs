//! Private exec boundary for ALSA helpers; no worker protocol output here.
use std::process::Command;
use anyhow::Result;

pub fn exec_parent_bound(_expected_parent: u32, command: &mut Command) -> Result<()> {
    use std::os::unix::process::CommandExt;
    Err(command.exec().into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;
    use std::process::{Child, Stdio};
    use std::thread;
    use std::time::{Duration, Instant};

    fn fixture(name: &str) -> Command {
        let mut command = Command::new(std::env::current_exe().unwrap());
        command.args(["--ignored", "--exact", name, "--nocapture"]);
        command.stdout(Stdio::null()).stderr(Stdio::null());
        command
    }
    fn wait_for(mut ready: impl FnMut() -> bool) -> bool {
        let deadline = Instant::now() + Duration::from_secs(5);
        while !ready() { if Instant::now() >= deadline { return false; } thread::sleep(Duration::from_millis(20)); } true
    }
    fn locked(path: &Path) -> bool {
        !Command::new("/usr/bin/flock").arg("-n").arg(path).arg("/bin/true").status().unwrap().success()
    }
    struct Reap(Child);
    impl Drop for Reap { fn drop(&mut self) { let _ = self.0.kill(); let _ = self.0.wait(); } }

    #[test]
    fn gsm_audio_helpers_release_both_endpoint_leases_after_worker_sigkill() {
        let dir = tempfile::tempdir().unwrap();
        let mut parent = Reap(fixture("gsm_audio_helper::tests::gsm_worker_fixture")
            .env("GSM_HELPER_TEST_DIR", dir.path()).spawn().unwrap());
        let capture = dir.path().join("capture"); let playback = dir.path().join("playback");
        assert!(wait_for(|| capture.exists() && playback.exists() && locked(&capture) && locked(&playback)), "fixture failed to acquire both endpoints");
        parent.0.kill().unwrap(); parent.0.wait().unwrap();
        assert!(wait_for(|| !locked(&capture) && !locked(&playback)), "orphaned audio helpers retained endpoint locks after worker SIGKILL");
    }

    #[test]
    fn gsm_audio_helper_refuses_stale_parent_before_opening_endpoint() {
        let dir = tempfile::tempdir().unwrap(); let path = dir.path().join("endpoint");
        let mut child = Reap(fixture("gsm_audio_helper::tests::gsm_relay_fixture")
            .env("GSM_HELPER_TEST_PARENT", "0").env("GSM_HELPER_TEST_PATH", &path).spawn().unwrap());
        assert!(wait_for(|| child.0.try_wait().unwrap().is_some()), "stale parent helper executed relay instead of refusing");
        assert!(!path.exists(), "stale helper acquired endpoint");
    }

    #[test]
    #[ignore = "subprocess fixture for forced-worker-exit test"]
    fn gsm_worker_fixture() {
        let dir = std::env::var_os("GSM_HELPER_TEST_DIR").unwrap();
        let mut children = Vec::new();
        for endpoint in ["capture", "playback"] {
            use std::os::unix::process::CommandExt;
            children.push(Reap(fixture("gsm_audio_helper::tests::gsm_relay_fixture")
                .env("GSM_HELPER_TEST_PARENT", std::process::id().to_string())
                .env("GSM_HELPER_TEST_PATH", Path::new(&dir).join(endpoint))
                .process_group(0).spawn().unwrap()));
        }
        thread::sleep(Duration::from_secs(15));
    }

    #[test]
    #[ignore = "subprocess fixture for helper exec and parent fence"]
    fn gsm_relay_fixture() {
        let parent = std::env::var("GSM_HELPER_TEST_PARENT").unwrap().parse().unwrap();
        let path = std::env::var_os("GSM_HELPER_TEST_PATH").unwrap();
        let mut command = Command::new("/usr/bin/flock");
        command.args(["--no-fork", "-x"]).arg(path).args(["/bin/sleep", "10"]);
        exec_parent_bound(parent, &mut command).unwrap();
    }
}

