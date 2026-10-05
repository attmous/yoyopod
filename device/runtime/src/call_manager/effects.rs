//! Typed command correlation. Request IDs are opaque; identity and purpose live here.
use super::{CallAction, CallManagerEvent, CallTransport, InterruptForCall, SessionKey};
use crate::event::RuntimeCommand;
use crate::protocol::{EnvelopeKind, WorkerEnvelope};
use crate::state::WorkerDomain;
use serde_json::{json, Value};
use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OperationPurpose {
    PrepareMedia,
    PrepareVoip,
    CancelSpeech,
    AlertRoute,
    StartRingtone(u64),
    StopRingtone(u64),
    Native(CallAction),
    Dial,
    Secondary(CallAction, u8),
    ReleaseMedia,
    ReleaseVoip,
    Admit,
}

#[derive(Debug, Clone)]
pub struct PendingOperation {
    pub key: SessionKey,
    pub purpose: OperationPurpose,
    pub request_id: String,
    pub domain: WorkerDomain,
    pub deadline_ms: u64,
    pub activity_generation: Option<u64>,
    worker_epoch: u64,
}

#[derive(Debug, Clone, Default)]
pub struct CallOperationLedger {
    operations: Vec<PendingOperation>,
    serial: u64,
    alert_epoch: u64,
    alert: Option<(SessionKey, u64)>,
    worker_epochs: HashMap<WorkerDomain, u64>,
}

pub fn domain_for(transport: &CallTransport) -> WorkerDomain {
    match transport {
        CallTransport::Sip => WorkerDomain::Voip,
        CallTransport::Gsm => WorkerDomain::Network,
    }
}

impl CallOperationLedger {
    pub fn command(
        &mut self,
        key: &SessionKey,
        purpose: OperationPurpose,
        domain: WorkerDomain,
        message_type: &str,
        payload: Value,
        now_ms: u64,
    ) -> RuntimeCommand {
        if purpose == OperationPurpose::AlertRoute {
            self.operations
                .retain(|p| p.key != *key || p.purpose != OperationPurpose::AlertRoute);
        }
        if matches!(
            purpose,
            OperationPurpose::Dial
                | OperationPurpose::Native(
                    CallAction::Answer | CallAction::Hangup | CallAction::Reject(_)
                )
        ) {
            self.operations.retain(|p| {
                p.key != *key
                    || !matches!(
                        p.purpose,
                        OperationPurpose::Dial | OperationPurpose::Native(_)
                    )
            });
        }
        self.serial = self
            .serial
            .checked_add(1)
            .expect("call operation counter exhausted");
        let request_id = format!("managed-{}", self.serial);
        self.operations.push(PendingOperation {
            key: key.clone(),
            purpose,
            request_id: request_id.clone(),
            domain,
            deadline_ms: now_ms.saturating_add(8_000),
            activity_generation: payload.get("activity_generation").and_then(Value::as_u64),
            worker_epoch: self.worker_epochs.get(&domain).copied().unwrap_or(0),
        });
        RuntimeCommand::WorkerCommand {
            domain,
            envelope: WorkerEnvelope::command(message_type, Some(request_id), payload),
        }
    }

    pub fn interrupt(
        &mut self,
        request: &InterruptForCall,
        domain: WorkerDomain,
        now_ms: u64,
    ) -> RuntimeCommand {
        let (purpose, name) = match domain {
            WorkerDomain::Media => (OperationPurpose::PrepareMedia, "media.interrupt_for_call"),
            WorkerDomain::Voip => (OperationPurpose::PrepareVoip, "voip.interrupt_for_call"),
            _ => unreachable!("only resource-owning audio workers interrupt"),
        };
        self.command(&request.key, purpose, domain, name, json!(request), now_ms)
    }

    pub fn next_alert(&mut self, key: &SessionKey) -> u64 {
        self.alert_epoch = self
            .alert_epoch
            .checked_add(1)
            .expect("alert counter exhausted");
        self.alert = Some((key.clone(), self.alert_epoch));
        self.alert_epoch
    }

    pub fn stop_alert(&mut self, key: &SessionKey) -> Option<u64> {
        let epoch = self.alert.as_ref().filter(|(k, _)| k == key)?.1;
        // A Stop supersedes every unresolved Start for exactly this alert epoch.
        self.operations
            .retain(|p| p.key != *key || p.purpose != OperationPurpose::StartRingtone(epoch));
        Some(epoch)
    }

    pub fn take(&mut self, domain: WorkerDomain, request_id: &str) -> Option<PendingOperation> {
        let index = self
            .operations
            .iter()
            .position(|p| p.domain == domain && p.request_id == request_id)?;
        Some(self.operations.remove(index))
    }

    pub fn result(
        &mut self,
        domain: WorkerDomain,
        envelope: &WorkerEnvelope,
    ) -> Option<(PendingOperation, bool)> {
        if !matches!(envelope.kind, EnvelopeKind::Result | EnvelopeKind::Error) {
            return None;
        }
        let operation = self.take(domain, envelope.request_id.as_deref()?)?;
        let mut ok = envelope.kind == EnvelopeKind::Result
            && envelope.payload.get("ok").and_then(Value::as_bool) != Some(false);
        let p = &envelope.payload;
        match &operation.purpose {
            OperationPurpose::PrepareMedia
            | OperationPurpose::PrepareVoip
            | OperationPurpose::ReleaseMedia
            | OperationPurpose::ReleaseVoip => {
                ok &= serde_json::from_value::<SessionKey>(p["key"].clone())
                    .ok()
                    .as_ref()
                    == Some(&operation.key);
                ok &= p["activity_generation"].as_u64() == operation.activity_generation;
                let field = if operation.purpose == OperationPurpose::ReleaseVoip {
                    "released"
                } else {
                    "audio_released"
                };
                ok &= p[field].as_bool() == Some(true);
            }
            OperationPurpose::StartRingtone(epoch) | OperationPurpose::StopRingtone(epoch) => {
                ok &= self.alert.as_ref() == Some(&(operation.key.clone(), *epoch));
                ok &= serde_json::from_value::<SessionKey>(p["key"].clone())
                    .ok()
                    .as_ref()
                    == Some(&operation.key);
                ok &= p["operation_generation"].as_u64() == Some(*epoch)
                    && p["ok"].as_bool() == Some(true);
            }
            OperationPurpose::CancelSpeech => {
                ok &= envelope.message_type == "voice.cancelled" && p["cancelled"].is_boolean();
            }
            OperationPurpose::Native(_)
            | OperationPurpose::Dial
            | OperationPurpose::Secondary(_, _)
                if domain == WorkerDomain::Network =>
            {
                ok &= serde_json::from_value::<SessionKey>(p["key"].clone())
                    .ok()
                    .as_ref()
                    == Some(&operation.key);
                ok &= p["ok"].as_bool() == Some(true);
            }
            _ => {}
        }
        Some((operation, ok))
    }

    pub fn expired(&mut self, now_ms: u64) -> Vec<PendingOperation> {
        let mut expired = vec![];
        self.operations.retain(|p| {
            if p.deadline_ms <= now_ms {
                expired.push(p.clone());
                false
            } else {
                true
            }
        });
        expired
    }
    pub fn invalidate(&mut self, key: &SessionKey) {
        self.operations.retain(|p| &p.key != key);
        if self.alert.as_ref().is_some_and(|(k, _)| k == key) {
            self.alert = None;
        }
    }
    pub fn invalidate_domain(&mut self, domain: WorkerDomain) -> Vec<PendingOperation> {
        *self.worker_epochs.entry(domain).or_default() += 1;
        let mut lost = vec![];
        self.operations.retain(|p| {
            if p.domain == domain {
                lost.push(p.clone());
                false
            } else {
                true
            }
        });
        lost
    }
    pub fn is_current(&self, operation: &PendingOperation) -> bool {
        operation.worker_epoch
            == self
                .worker_epochs
                .get(&operation.domain)
                .copied()
                .unwrap_or(0)
    }
    pub fn native_event(operation: &PendingOperation, ok: bool) -> Option<CallManagerEvent> {
        matches!(
            operation.purpose,
            OperationPurpose::Native(
                CallAction::Answer | CallAction::Hangup | CallAction::Reject(_)
            ) | OperationPurpose::Dial
        )
        .then(|| CallManagerEvent::CommandFinished {
            key: operation.key.clone(),
            request_id: operation.request_id.clone(),
            ok,
        })
    }
}
