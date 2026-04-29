#![cfg(all(target_os = "linux", feature = "whisplay-hardware"))]

use yoyopod_ui_host::hardware::whisplay::spi_chunks;
use yoyopod_ui_host::whisplay_panel::{HEIGHT, WIDTH};

#[test]
fn chunks_full_frame_under_linux_spi_message_limit() {
    let payload = vec![0u8; WIDTH * HEIGHT * 2];
    let chunk_lengths: Vec<usize> = spi_chunks(&payload).map(|chunk| chunk.len()).collect();

    assert!(chunk_lengths.iter().all(|length| *length <= 4096));
    assert_eq!(chunk_lengths.iter().sum::<usize>(), payload.len());
    assert_eq!(chunk_lengths[0], 4096);
    assert_eq!(*chunk_lengths.last().unwrap(), 3328);
}
