"""
Tests for the restocking order endpoints.
"""
import pytest
import mock_data


@pytest.fixture(autouse=True)
def reset_restock_orders():
    """restock_orders is an in-memory list with no built-in reset between tests."""
    mock_data.restock_orders.clear()
    yield
    mock_data.restock_orders.clear()


def sample_item(quantity=10, unit_cost=24.99):
    return {
        "sku": "PCB-001",
        "name": "Single Layer PCB Assembly",
        "quantity": quantity,
        "unit_cost": unit_cost,
        "line_total": round(quantity * unit_cost, 2)
    }


class TestGetRestockOrders:
    """Test suite for listing submitted restock orders."""

    def test_get_restock_orders_empty(self, client):
        response = client.get("/api/restock-orders")
        assert response.status_code == 200
        assert response.json() == []


class TestCreateRestockOrder:
    """Test suite for submitting restock orders."""

    def test_create_restock_order_success(self, client):
        payload = {"budget": 5000, "items": [sample_item(quantity=10, unit_cost=24.99)]}
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 201

        data = response.json()
        assert data["order_number"] == "RST-0001"
        assert data["status"] == "Submitted"
        assert 7 <= data["lead_time_days"] <= 21
        assert data["total_value"] == round(10 * 24.99, 2)
        assert data["expected_delivery"] > data["order_date"]

    def test_create_restock_order_recomputes_total_server_side(self, client):
        """Client-sent line_total/total should never be trusted."""
        item = sample_item(quantity=10, unit_cost=24.99)
        payload = {"budget": 5000, "items": [item]}
        response = client.post("/api/restock-orders", json=payload)
        data = response.json()

        assert data["items"][0]["line_total"] == round(10 * 24.99, 2)
        assert data["total_value"] == round(10 * 24.99, 2)

    def test_create_restock_order_empty_items_rejected(self, client):
        response = client.post("/api/restock-orders", json={"budget": 5000, "items": []})
        assert response.status_code == 400

    def test_create_restock_order_unknown_sku_rejected(self, client):
        item = sample_item()
        item["sku"] = "NOT-A-REAL-SKU"
        response = client.post("/api/restock-orders", json={"budget": 5000, "items": [item]})
        assert response.status_code == 400

    def test_create_restock_order_non_positive_quantity_rejected(self, client):
        item = sample_item(quantity=0)
        response = client.post("/api/restock-orders", json={"budget": 5000, "items": [item]})
        assert response.status_code == 422

    def test_create_restock_order_negative_budget_rejected(self, client):
        payload = {"budget": -100, "items": [sample_item()]}
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 422

    def test_create_restock_order_sequential_order_numbers(self, client):
        payload = {"budget": 5000, "items": [sample_item()]}
        first = client.post("/api/restock-orders", json=payload).json()
        second = client.post("/api/restock-orders", json=payload).json()

        assert first["order_number"] == "RST-0001"
        assert second["order_number"] == "RST-0002"

    def test_create_restock_order_appears_in_get(self, client):
        payload = {"budget": 5000, "items": [sample_item()]}
        created = client.post("/api/restock-orders", json=payload).json()

        response = client.get("/api/restock-orders")
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == created["id"]
