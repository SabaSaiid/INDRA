"""
Alert Engine — Integration Tests: Persistent Store
"""

import pytest
import pytest_asyncio

from alert_engine.engine.lifecycle import LifecycleManager
from alert_engine.models import AlertStatus, EscalationLevel
from alert_engine.rules.registry import get_active_rules


class TestPersistentStore:
    @pytest.mark.asyncio
    async def test_save_and_retrieve_alert_by_fingerprint(self, store, patna_event):
        rule = get_active_rules()[0]
        lm = LifecycleManager()
        alert, _ = lm.create_alert(patna_event, rule, "Test")

        await store.save_alert(alert)
        retrieved = await store.get_alert_by_fingerprint(alert.fingerprint)

        assert retrieved is not None
        assert retrieved.alert_id == alert.alert_id
        assert retrieved.status == AlertStatus.ACTIVE
        assert retrieved.confidence == alert.confidence
        assert retrieved.source_count == alert.source_count

    @pytest.mark.asyncio
    async def test_retrieve_returns_none_for_unknown_fingerprint(self, store):
        result = await store.get_alert_by_fingerprint("nonexistent-fingerprint")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_alert_for_event(self, store, patna_event):
        rule = get_active_rules()[0]
        lm = LifecycleManager()
        alert, _ = lm.create_alert(patna_event, rule, "Test")
        await store.save_alert(alert)

        found = await store.get_active_alert_for_event(patna_event.event_code)
        assert found is not None
        assert found.alert_id == alert.alert_id

    @pytest.mark.asyncio
    async def test_get_active_alert_for_nonexistent_event(self, store):
        found = await store.get_active_alert_for_event("NONEXISTENT-EVENT-CODE")
        assert found is None

    @pytest.mark.asyncio
    async def test_list_active_alerts(self, store, patna_event):
        rule = get_active_rules()[0]
        lm = LifecycleManager()
        alert, _ = lm.create_alert(patna_event, rule, "Test")
        await store.save_alert(alert)

        actives = await store.list_active_alerts()
        assert any(a.alert_id == alert.alert_id for a in actives)

    @pytest.mark.asyncio
    async def test_resolved_alert_not_in_active_list(self, store, patna_event):
        rule = get_active_rules()[0]
        lm = LifecycleManager()
        alert, _ = lm.create_alert(patna_event, rule, "Test")
        history = lm.resolve_alert(alert, "Test resolution")
        await store.save_alert(alert)
        await store.save_history(history)

        actives = await store.list_active_alerts()
        alert_ids = [a.alert_id for a in actives]
        assert alert.alert_id not in alert_ids

    @pytest.mark.asyncio
    async def test_save_and_retrieve_history(self, store, patna_event):
        import aiosqlite
        rule = get_active_rules()[0]
        lm = LifecycleManager()
        alert, history = lm.create_alert(patna_event, rule, "Test")

        await store.save_alert(alert)
        await store.save_history(history)

        async with aiosqlite.connect(store.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM alert_history WHERE alert_id = ?", (alert.alert_id,)
            ) as cursor:
                rows = await cursor.fetchall()

        assert len(rows) == 1
        assert rows[0]["previous_status"] == "NONE"
        assert rows[0]["new_status"] == AlertStatus.ACTIVE.value
        assert rows[0]["actor"] == "system"

    @pytest.mark.asyncio
    async def test_state_recovery_after_close_reopen(self, temp_db, patna_event):
        """Simulates a restart: write, close, reopen, verify data is intact."""
        from alert_engine.state.persistent_store import PersistentStore

        rule = get_active_rules()[0]
        lm = LifecycleManager()
        alert, _ = lm.create_alert(patna_event, rule, "Test")

        # First store instance — write
        store1 = PersistentStore(temp_db)
        await store1.init_db()
        await store1.save_alert(alert)

        # Second store instance — simulates a service restart
        store2 = PersistentStore(temp_db)
        await store2.init_db()
        recovered = await store2.get_alert_by_fingerprint(alert.fingerprint)

        assert recovered is not None
        assert recovered.alert_id == alert.alert_id
        assert recovered.event_code == patna_event.event_code
        assert recovered.severity == patna_event.severity

    @pytest.mark.asyncio
    async def test_escalated_alert_in_active_list(self, store, patna_event):
        rule = get_active_rules()[0]
        lm = LifecycleManager()
        alert, _ = lm.create_alert(patna_event, rule, "Test")
        # Escalate it
        lm.escalate_alert(alert, patna_event, "LEVEL_1", "Severity increase")
        await store.save_alert(alert)

        actives = await store.list_active_alerts()
        assert any(a.alert_id == alert.alert_id for a in actives)
        found = next(a for a in actives if a.alert_id == alert.alert_id)
        assert found.status == AlertStatus.ESCALATED

    @pytest.mark.asyncio
    async def test_mode_filter_in_list_active(self, store, patna_event):
        rule = get_active_rules()[0]
        lm = LifecycleManager()
        alert, _ = lm.create_alert(patna_event, rule, "Test")
        # mode is derived from raw_source="api" -> alert.mode="api"
        await store.save_alert(alert)

        # Filter by wrong mode — should return empty
        actives = await store.list_active_alerts(mode="live")
        assert not any(a.alert_id == alert.alert_id for a in actives)

        # Filter by correct mode
        actives = await store.list_active_alerts(mode="api")
        assert any(a.alert_id == alert.alert_id for a in actives)
