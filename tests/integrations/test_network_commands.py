"""Focused tests for scaffold network command dataclasses."""

from __future__ import annotations

from yoyopod.integrations.network.commands import (
    DisablePppCommand,
    EnablePppCommand,
    RefreshSignalCommand,
    SetApnCommand,
)


def test_enable_ppp_command() -> None:
    assert EnablePppCommand() is not None


def test_disable_ppp_command() -> None:
    assert DisablePppCommand() is not None


def test_refresh_signal_command() -> None:
    assert RefreshSignalCommand() is not None


def test_set_apn_command() -> None:
    command = SetApnCommand(apn="internet.provider.com", username="u", password="p")
    assert command.apn == "internet.provider.com"
    assert command.username == "u"
    assert command.password == "p"


def test_set_apn_command_defaults_empty() -> None:
    command = SetApnCommand(apn="internet")
    assert command.username == ""
    assert command.password == ""
