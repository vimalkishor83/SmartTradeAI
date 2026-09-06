from pathlib import Path


TEMPLATE = Path("frontend/templates/dashboard/broker_connections.html")


def test_broker_connections_uses_delegated_actions_and_safe_rendering():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onchange=" not in source
    assert 'data-action="test-broker"' in source
    assert 'data-action="disconnect-broker"' in source
    assert 'data-action="connect-broker"' in source
    assert 'form="connectForm"' in source
    assert "addEventListener('submit', submitConnection)" in source
    assert "_brokerMutations" in source
    assert "brokerEscape(c.provider_label)" in source
    assert "brokerEscape(b.help)" in source
    assert 'id="brokerConnectionsStatus" class="visually-hidden" role="status" aria-live="polite"' in source
    assert 'caption class="visually-hidden"' in source
    assert 'aria-label="Disconnect ${brokerEscape(c.provider_label)}"' in source


def test_broker_connections_validates_provider_urls_and_request_order():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function brokerUrl(value)" in source
    assert "['http:', 'https:'].includes(url.protocol)" in source
    assert "function providerMeta(provider)" in source
    assert "_brokerCatalogSequence" in source
    assert "_brokerConnectionSequence" in source
    assert "Promise.allSettled([loadBrokers(), loadConnections()])" in source
    assert "value.length > 1024" in source
    assert "[\\u0000-\\u001f]" in source
    assert "Broker connections are unavailable." in source
    assert "Broker catalog is unavailable." in source
