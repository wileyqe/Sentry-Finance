"""Tests for transfer reconciliation logic."""

import pytest
import sqlite3
import uuid
from unittest.mock import patch
from dal.migrations import init_db
from dal.reconciliation import reconcile_transfers

import tempfile
import os

@pytest.fixture
def memory_db():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        db_path = f.name
        
    init_db(db_path)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    
    conn.close()
    try:
        os.remove(db_path)
    except OSError:
        pass

def insert_txn(conn, account_id, inst_id, amount, direction, desc, date, category="Uncategorized", tag=None):
    txn_id = "txn-" + str(uuid.uuid4())[:8]
    conn.execute(
        """
        INSERT INTO transactions (id, account_id, institution_id, posting_date, amount, signed_amount, direction, description, category, transfer_tag, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'posted')
        """,
        (
            txn_id, account_id, inst_id, date, amount, 
            amount if direction == "credit" else -amount, 
            direction, desc, category, tag
        )
    )
    return txn_id

# Test 1: Basic cross-institution transfer
# NFCU checking debit $500 + Chase checking credit $500 within 2 days -> should be tagged
def test_cross_institution_transfer(memory_db):
    t1 = insert_txn(memory_db, "a1", "inst_nfcu", 500.0, "debit", "transfer to chase", "2023-10-01")
    t2 = insert_txn(memory_db, "a2", "inst_chase", 500.0, "credit", "transfer from nfcu", "2023-10-03")
    
    stats = reconcile_transfers(memory_db)
    assert stats["newly_tagged"] == 1
    
    res = memory_db.execute("SELECT transfer_tag FROM transactions WHERE id IN (?, ?)", (t1, t2)).fetchall()
    tags = [r["transfer_tag"] for r in res]
    assert len(tags) == 2
    assert tags[0] is not None
    assert tags[0] == tags[1]

# Test 2: Same-institution transfer (new feature)
# NFCU NFCB debit $2000 + NFCU NFCA credit $2000 same day -> should be tagged as a pair
def test_same_institution_transfer(memory_db):
    t1 = insert_txn(memory_db, "NFCB", "inst_nfcu", 2000.0, "debit", "internal transfer", "2023-10-01")
    t2 = insert_txn(memory_db, "NFCA", "inst_nfcu", 2000.0, "credit", "internal transfer", "2023-10-01")
    
    stats = reconcile_transfers(memory_db)
    assert stats["newly_tagged"] == 1
    
    res = memory_db.execute("SELECT transfer_tag FROM transactions WHERE id IN (?, ?)", (t1, t2)).fetchall()
    tags = [r["transfer_tag"] for r in res]
    assert len(tags) == 2
    assert tags[0] is not None
    assert tags[0] == tags[1]

# Test 3: Amount mismatch - should NOT match
# NFCU debit $500 + Chase credit $501 -> no match
def test_amount_mismatch(memory_db):
    t1 = insert_txn(memory_db, "a1", "inst_nfcu", 500.0, "debit", "transfer to chase", "2023-10-01")
    t2 = insert_txn(memory_db, "a2", "inst_chase", 501.0, "credit", "transfer from nfcu", "2023-10-01")
    
    stats = reconcile_transfers(memory_db)
    assert stats["newly_tagged"] == 0

# Test 4: Same direction - should NOT match
# NFCU debit $500 + Chase debit $500 -> no match
def test_same_direction(memory_db):
    t1 = insert_txn(memory_db, "a1", "inst_nfcu", 500.0, "debit", "transfer to chase", "2023-10-01")
    t2 = insert_txn(memory_db, "a2", "inst_chase", 500.0, "debit", "transfer from nfcu", "2023-10-01")
    
    stats = reconcile_transfers(memory_db)
    assert stats["newly_tagged"] == 0

# Test 5: Too far apart in time - should NOT match
# NFCU debit $500 (Jan 1) + Chase credit $500 (Jan 10) -> no match
def test_too_far_apart(memory_db):
    t1 = insert_txn(memory_db, "a1", "inst_nfcu", 500.0, "debit", "transfer to chase", "2023-01-01")
    t2 = insert_txn(memory_db, "a2", "inst_chase", 500.0, "credit", "transfer from nfcu", "2023-01-10")
    
    stats = reconcile_transfers(memory_db)
    assert stats["newly_tagged"] == 0

# Test 6: No transfer keyword on either - should NOT match
# NFCU debit $100 "GROCERY STORE" + Chase credit $100 "REFUND" -> no match
def test_no_transfer_keyword(memory_db):
    t1 = insert_txn(memory_db, "a1", "inst_nfcu", 100.0, "debit", "GROCERY STORE", "2023-10-01")
    t2 = insert_txn(memory_db, "a2", "inst_chase", 100.0, "credit", "REFUND", "2023-10-01")
    
    stats = reconcile_transfers(memory_db)
    assert stats["newly_tagged"] == 0

# Test 7: Already tagged - should count as already_tagged, not newly_tagged
def test_already_tagged(memory_db):
    existing_tag = "tag-1234"
    t1 = insert_txn(memory_db, "a1", "inst_nfcu", 500.0, "debit", "transfer out", "2023-10-01", tag=existing_tag)
    t2 = insert_txn(memory_db, "a2", "inst_chase", 500.0, "credit", "transfer in", "2023-10-01", tag=existing_tag)
    
    stats = reconcile_transfers(memory_db)
    assert stats["newly_tagged"] == 0
    assert stats["already_tagged"] == 1
