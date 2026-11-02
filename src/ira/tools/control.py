"""Turning control of a device on and off by asking: "mera Mac control karo, 30 minute".

Turning it on is Tier 3, so it takes the person's PIN on a card, from any of their devices; what
a page or a screen says can never ask for it. It opens the approval window that
``ira.approvals`` keeps (docs/security.md, "Approvals"). Turning it off needs nothing.
"""

from __future__ import annotations

from typing import Any

from ira.approvals import valid_minutes
from ira.tools.personal import PersonalTool
from ira.tools.registry import ToolError

DEFAULT_MINUTES = 30
OPENED = {"type": "control", "open": True}
CLOSED = {"type": "control", "open": False}


def control_tools(runtime: Any, user_id: int) -> list[PersonalTool]:
    """Offered to a person with a device that can be controlled."""
    hub, approvals = runtime.hub, runtime.approvals
    devices = [
        device
        for device in hub.devices.for_user(user_id)
        if "control" in device.skills
        and any(tool.get("skill") == "control" for tool in device.tools)
    ]
    if not devices:
        return []
    labels = {device.label: device.id for device in devices}

    async def start(arguments: dict[str, Any]) -> Any:
        wanted = str(arguments.get("device") or "")
        device_id = labels.get(wanted) if wanted else devices[0].id
        if device_id is None:
            raise ToolError(f"no device of yours can be controlled by that name: {wanted}")
        minutes = int(arguments.get("minutes") or DEFAULT_MINUTES)
        if not valid_minutes(minutes) or minutes == 0:
            raise ToolError("minutes must be 5 to 60")
        if not hub.connected(device_id):
            raise ToolError(f"{runtime.device_label(device_id)} is offline right now")
        window = approvals.open(user_id, device_id, None, minutes=minutes)
        await hub.send_to_person(user_id, OPENED)
        return {
            "window": window.id if window else None,
            "summary": f"Ira can control {runtime.device_label(device_id)} for {minutes} minutes. "
            "It shows a banner with Stop there, and ends by itself.",
        }

    async def stop(arguments: dict[str, Any]) -> Any:
        stopped = approvals.stop(user_id)
        await hub.send_to_person(user_id, CLOSED)
        return {"stopped": stopped, "summary": "Control is off." if stopped else "It was off."}

    properties: dict[str, Any] = {
        "minutes": {
            "type": "integer",
            "minimum": 5,
            "maximum": 60,
            "description": f"How long, from 5 to 60 (default {DEFAULT_MINUTES}).",
        },
    }
    if len(labels) > 1:
        properties["device"] = {
            "type": "string",
            "enum": sorted(labels),
            "description": "Which device.",
        }
    return [
        PersonalTool(
            name="control_start",
            description="Let Ira operate one of the person's computers without asking at each "
            "step, for a length they pick, only when they ask for it in so many words. It "
            "takes their PIN once. Sending, paying, buying and deleting still ask.",
            parameters={"type": "object", "properties": properties},
            tier=3,
            source="ira",
            label="Ira",
            run=start,
            skill="control",
        ),
        PersonalTool(
            name="control_stop",
            description="End Ira's control of the person's devices at once.",
            parameters={"type": "object", "properties": {}},
            tier=0,
            source="ira",
            label="Ira",
            run=stop,
            skill="control",
        ),
    ]
