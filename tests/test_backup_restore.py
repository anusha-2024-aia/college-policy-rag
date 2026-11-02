"""Automated verification of disaster recovery, backup, and restore procedures."""

from scripts.drill_backup_restore import run_drill


def test_disaster_recovery_backup_and_restore_drill():
    """Verify that backup and restore into an empty database succeeds with 100% data integrity."""
    result = run_drill()
    assert result["status"] == "SUCCESS"
    assert result["table_counts"]["documents"] == 16
    assert result["table_counts"]["chunks"] == 51
    assert result["table_counts"]["chunks_semantic"] == 51
    assert result["table_counts"]["document_lineage"] == 3
    assert result["table_counts"]["users"] == 3
    assert result["table_counts"]["embedding_index_metadata"] == 1
    assert "Academic Regulations" in result["sample_document"]

