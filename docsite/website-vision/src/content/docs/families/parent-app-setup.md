---
title: The Parent App & Pairing
description: Connect your phone to the device and take the controls.
---

*Pair the parent app with the device and complete the family's first configuration.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything on it is proposed — neither implemented
nor committed.
:::

## What you'll need

You'll need the device powered on and sitting on its Setup screen, showing
its short claim code — that's where [Unboxing & First
Setup](/families/unboxing/) left you. You'll need a phone, iPhone or
Android; it's the same yoyopod app on both, and a household with one of
each is completely normal.

You will *not* need to invent a password. Your account uses a passkey —
your phone's own face or fingerprint unlock — so there's nothing to make
up, write down, or forget.

The device does need mobile coverage during pairing, because your phone
and the device never talk to each other directly — everything goes through
yoyocloud, our service in the middle. That's a feature, not a limitation:
it means pairing works exactly the same whether you're beside the device
or, one day, helping a grandparent set one up over a phone call.

Set aside about ten minutes. Ideally do it at the table with the kid
watching — this is the moment their device joins the family.

## Steps

**Install the yoyopod app.** Search "yoyopod" in the App Store or Google
Play. One app for the whole household — every parent installs the same
one.

**Create your parent account.** The app asks for your email and then your
phone does the rest: a passkey is created and confirmed with your face or
fingerprint. No password to invent, nothing to reuse from another site,
nothing for anyone to phish later.

**Set up your household.** A household is the home for your family's
parents and devices. You create it once; a second parent or caregiver
joins the same household later from the app, with equal say — both of you
see the same devices and can change the same settings.

**Add your kid.** This step is shorter than you expect: a first name and
an age band. That's all, and that's deliberate — the device doesn't need a
birthday, a photo, or a surname to do its job, so we never ask for them.

**Enter the claim code.** The device has been showing a short code on its
canvas since it reached the Setup screen. Type it into the app, or scan
it. The app sends the code up to yoyocloud, yoyocloud checks that this
device really is the one showing that code, and binds it to your
household. The canvas confirms with a little celebration, and from that
moment the device appears in your app. You can give it a name here —
"Mia's yoyopod" — so it's unmistakable if the household ever has two.

**Build the first whitelist.** The whitelist is the short list of people
the device can call and exchange voice notes with — and the only people
who can reach it. Start small: you, the other parent, maybe one
grandparent. You can grow it any time. As you save each contact, the app
shows two honest states: **saved** (yoyocloud has it) and **active on
device** (the device has confirmed it) — so you always know what the
device is actually enforcing, even if it's briefly offline.

**Load something to listen to.** Put the first music and stories on the
device from the app. Content lives *on the device*, which means the
listening half of the product works with no internet at all — in the
basement, on a plane, anywhere. More on everyday listening at
[Listening](/families/listening/).

**Glance at the location view.** Before the first solo outing, open the
location tab once so you know what it looks like. It shows roughly where
the device is and when it last checked in — periodic, unhurried updates,
not a live track. What it shows and why is explained at
[Location](/families/location/).

**You're done when:**

- The app is installed and your account opens with a passkey
- Your kid is added — first name and age band
- The device is paired, named, and shows as online in the app
- The whitelist has at least one contact marked *active on device*
- There's something loaded to listen to
- You've seen the location view once

## Tips

Do the pairing together. The moment the code on the kid's canvas turns
into "their device" inside your phone is a genuinely nice one, and a kid
who watched it happen understands the device is connected to *family*,
not to the internet at large.

Start the whitelist small and grow it on request. "Can we add Uncle
Jonas?" a week in is a lovely conversation; pruning a too-long list is
not.

Invite the second parent early. Same household, same app, equal rights —
the invitation lives in the app's household screen, and two configured
phones beat one from the first day.

Bookmark [Parental Controls](/families/parental-controls/). Everything you
just set — whitelist, location, content, the Ask helpers — lives there,
and nothing you chose today is permanent. First setup is a starting
point, not a contract.

## Troubleshooting

**The app won't accept the code.** The app never searches for the device —
it simply asks yoyocloud, so a rejected code usually means yoyocloud can't
see the device yet. Check the canvas is actually on the Setup screen
showing its code, give the device a minute near a window if coverage is
thin, and try again. Codes are short-lived by design, so if some time has
passed, use the fresh one on the canvas.

**Pairing worked, but the device shows as offline.** Almost always
coverage. Nothing is lost: every change you make is marked *saved* in the
app and becomes *active on device* the moment the device next connects.
Meanwhile the device carries on happily — music, stories, and its
last-known family list all work without a connection.

**New phone, or reinstalled the app.** Sign back in with your passkey —
your household, your kid's profile, the whitelist, and the device are all
exactly where you left them. There's nothing to re-pair; pairing binds the
device to your *household*, not to a particular phone.

**No coverage at all where you are.** Pairing is the one moment that
genuinely needs the device online, because yoyocloud has to verify the
code the canvas is showing. If home is a dead zone, do the pairing
step anywhere with a bar of signal — a café, the car park — and finish the
rest at home; everything after the bind tolerates being offline.

## Open questions

- **Passkey recovery — adopt a second registered device, a printed
  recovery code in the box, or both?** Recovery is the real front door to
  the account; the choice deserves the same scrutiny as login itself.
- **Adopt a mandatory minimum before leaving Setup — at least one
  whitelist contact — or allow an empty circle?** Requiring one contact
  guarantees the device is never reachable-by-nobody; allowing zero
  respects families who want a listen-only start.
- **Scan-first or type-first for the claim code?** Scanning is faster and
  error-proof but needs the camera permission conversation; typing a short
  code is humble and always works. Adopt one as the primary path.
- **Invite the second parent during first setup, or keep first-run
  single-parent and surface the invitation afterwards?** In-flow
  invitations set the equal-rights household up correctly from minute one
  but lengthen exactly the flow we want shortest.
