from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import create_tank
from homeassistant.components import frontend
from homeassistant.exceptions import Unauthorized
from test_ha import add_consumer, call

from custom_components.ha_tankdata.panel import get_history, get_tanks


async def test_panel_api_isolation_pagination_and_permissions(hass):
    a = await create_tank(hass, "First")
    b = await create_tank(hass, "Second")
    await add_consumer(hass, a)
    for i in range(3):
        await call(hass, a, "record_refill", liters=1, event_id=f"refill-{i}")
    connection = Mock(user=SimpleNamespace(is_admin=True))
    get_tanks(hass, connection, {"id": 1})
    result = connection.send_result.call_args.args[1]
    assert [t["stock"] for t in result["tanks"]] == [503, 500]
    assert len(result["tanks"][0]["consumers"]) == 1
    get_history(hass, connection, {"id": 2, "config_entry_id": a.entry_id, "limit": 2})
    page = connection.send_result.call_args.args[1]
    assert [e["id"] for e in page["events"]] == ["refill-2", "refill-1"]
    await call(hass, a, "record_refill", liters=1, event_id="newer")
    get_history(
        hass,
        connection,
        {"id": 3, "config_entry_id": a.entry_id, "limit": 2, "before": page["before"]},
    )
    assert [e["id"] for e in connection.send_result.call_args.args[1]["events"]] == [
        "refill-0"
    ]
    get_history(hass, connection, {"id": 4, "config_entry_id": b.entry_id, "limit": 2})
    assert connection.send_result.call_args.args[1]["events"] == []
    for handler, message in [
        (get_tanks, {"id": 5}),
        (get_history, {"id": 6, "config_entry_id": a.entry_id}),
    ]:
        with pytest.raises(Unauthorized):
            handler(hass, Mock(user=SimpleNamespace(is_admin=False)), message)
    assert "tankdata" in hass.data[frontend.DATA_PANELS]
    assert await hass.config_entries.async_reload(a.entry_id)
    assert "tankdata" in hass.data[frontend.DATA_PANELS]
    await hass.config_entries.async_remove(a.entry_id)
    assert "tankdata" in hass.data[frontend.DATA_PANELS]
    await hass.config_entries.async_remove(b.entry_id)
    assert "tankdata" not in hass.data[frontend.DATA_PANELS]
    await create_tank(hass, "New")
    assert "tankdata" in hass.data[frontend.DATA_PANELS]


async def test_history_rejects_unloaded_and_missing_tanks(hass):
    entry = await create_tank(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    connection = Mock(user=SimpleNamespace(is_admin=True))
    for eid in [entry.entry_id, "missing"]:
        get_history(hass, connection, {"id": 1, "config_entry_id": eid, "limit": 50})
        assert connection.send_error.call_args.args[1] == "not_loaded"
