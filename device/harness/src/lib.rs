use serde_json::Value;
use yoyopod_protocol::WorkerEnvelope;

pub fn decode_envelopes(output: &[u8]) -> Vec<WorkerEnvelope> {
    worker_output_text(output)
        .lines()
        .enumerate()
        .map(|(index, line)| {
            WorkerEnvelope::decode(line.as_bytes()).unwrap_or_else(|error| {
                panic!(
                    "decode worker envelope on line {} failed: {error}; line: {line}",
                    index + 1
                )
            })
        })
        .collect()
}

pub fn decode_values(output: &[u8]) -> Vec<Value> {
    worker_output_text(output)
        .lines()
        .enumerate()
        .map(|(index, line)| {
            serde_json::from_str(line).unwrap_or_else(|error| {
                panic!(
                    "decode worker JSON line {} failed: {error}; line: {line}",
                    index + 1
                )
            })
        })
        .collect()
}

fn worker_output_text(output: &[u8]) -> String {
    String::from_utf8(output.to_vec()).unwrap_or_else(|error| {
        panic!(
            "worker output should be utf8: {error}; raw output: {:?}",
            error.as_bytes()
        )
    })
}

pub fn find_envelope<'a>(
    envelopes: &'a [WorkerEnvelope],
    message_type: &str,
) -> &'a WorkerEnvelope {
    envelopes
        .iter()
        .find(|envelope| envelope.message_type == message_type)
        .unwrap_or_else(|| {
            panic!("missing envelope type {message_type}; observed envelopes: {envelopes:#?}")
        })
}

pub fn find_value<'a>(values: &'a [Value], message_type: &str) -> &'a Value {
    values
        .iter()
        .find(|value| value["type"] == message_type)
        .unwrap_or_else(|| {
            panic!("missing JSON envelope type {message_type}; observed values: {values:#?}")
        })
}
