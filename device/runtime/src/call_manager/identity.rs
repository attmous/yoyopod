use super::{CallTransport, ContactIdentity};

fn phone(value: &str) -> Option<String> {
    let value = value.trim();
    if !value.starts_with('+') {
        return None;
    }
    let mut digits = String::from("+");
    for c in value[1..].chars() {
        if c.is_ascii_digit() {
            digits.push(c);
        } else if !matches!(c, ' ' | '-' | '(' | ')' | '.') {
            return None;
        }
    }
    let count = digits.len() - 1;
    ((7..=15).contains(&count) && !digits.starts_with("+0")).then_some(digits)
}
fn sip(value: &str) -> Option<String> {
    let value = value.trim();
    let (scheme, rest) = value.split_once(':')?;
    let scheme = scheme.to_ascii_lowercase();
    if scheme != "sip" && scheme != "sips" {
        return None;
    }
    let (user, host) = rest.split_once('@')?;
    if user.is_empty()
        || host.is_empty()
        || rest.chars().any(|c| {
            c.is_whitespace() || c.is_control() || matches!(c, '<' | '>' | ';' | '?' | '#')
        })
        || host.contains('@')
    {
        return None;
    }
    if !host
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | ':'))
    {
        return None;
    }
    let (hostname, port) = host
        .split_once(':')
        .map_or((host, None), |(h, p)| (h, Some(p)));
    if hostname
        .split('.')
        .any(|label| label.is_empty() || label.starts_with('-') || label.ends_with('-'))
        || port.is_some_and(|p| p.parse::<u16>().map_or(true, |port| port == 0))
    {
        return None;
    }
    Some(format!("{scheme}:{user}@{}", host.to_ascii_lowercase()))
}
pub fn match_contact<'a>(
    transport: CallTransport,
    address: &str,
    contacts: &'a [ContactIdentity],
) -> Option<&'a ContactIdentity> {
    let normalize = match transport {
        CallTransport::Sip => sip,
        CallTransport::Gsm => phone,
    };
    let target = normalize(address)?;
    let mut matches = contacts.iter().filter(|c| {
        normalize(match transport {
            CallTransport::Sip => &c.sip_address,
            CallTransport::Gsm => &c.phone_number,
        })
        .as_ref()
            == Some(&target)
    });
    let contact = matches.next()?;
    matches.next().is_none().then_some(contact)
}
