from scripts.audit_number_trust_dom import orphan_dom_builders, referenced_dom_builders


def test_dom_builders_are_referenced_by_registry():
    assert orphan_dom_builders() == []


def test_dom_builder_reference_check_reports_orphans():
    registry = {
        "surfaces": [
            {
                "values": [
                    {
                        "audit_stage": "api_oracle",
                        "dom_builder": "dashboard_supporting_metric",
                    }
                ]
            }
        ]
    }

    assert referenced_dom_builders(registry) == {"dashboard_supporting_metric"}
    assert "transactions_table_metric" in orphan_dom_builders(registry)
