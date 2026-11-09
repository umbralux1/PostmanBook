from app.services.localize import fill_base_url


def test_fill_base_url_recursively() -> None:
    data = {
        "hint": "Отправь на {{BASE_URL}}/api/echo",
        "steps": [[{"path": "body.path", "equals": "/api/echo", "hint": "{{BASE_URL}}/x"}]],
        "n": 200,
    }
    out = fill_base_url(data, "https://trainer.example.com")
    assert out["hint"] == "Отправь на https://trainer.example.com/api/echo"
    assert out["steps"][0][0] == {
        "path": "body.path",
        "equals": "/api/echo",
        "hint": "https://trainer.example.com/x",
    }
    assert out["n"] == 200
    assert data["hint"].startswith("Отправь на {{BASE_URL}}"), "исходные данные не меняются"
